"""用例集 dev / held-out 切分单测（change evals-dataset-scaleup-heldout）。

覆盖三块，全程离线、不触网、不依赖真实 provider：
- load_cases：split 字段加载校验（合法值归类、缺省归 dev、非法值报行号）。
- _filter_by_split：三种开关组合(默认 dev / --include-heldout / --heldout-only)的纯函数过滤。
- _split_results：把同序的 results 按用例 split 拆成 (dev, held-out)——这是「基线/门禁恒基于
  dev、held-out 物理上进不去 baseline_dict」这一约束的落地点，故单独验证其正确性与顺序保持。
"""

import pytest

from evals.metrics import EvalResult, build_report, report_to_baseline
from domains import load_domain
from evals.run_evals import _filter_by_split, _split_results, load_cases

# 标签白名单随域声明（change oncall-evals-bootstrap）。显式取预约域的那份：本文件的用例
# 字面量用的是预约域标签，而 load_cases 缺省取当前 AGENT_DOMAIN 装的域，会跟着 .env 飘。
_LABELS = load_domain("appointment").eval_profile.labels


def _write_cases(tmp_path, lines: list[str]):
    p = tmp_path / "cases.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# ── load_cases：split 字段校验 ────────────────────────────────────────────────

def test_load_case_with_explicit_dev_split(tmp_path):
    path = _write_cases(
        tmp_path, ['{"input": "你好", "expected_intent": "other", "split": "dev"}']
    )
    cases = load_cases(path, _LABELS)
    assert cases[0]["split"] == "dev"


def test_load_case_with_explicit_heldout_split(tmp_path):
    path = _write_cases(
        tmp_path, ['{"input": "你好", "expected_intent": "other", "split": "held-out"}']
    )
    cases = load_cases(path, _LABELS)
    assert cases[0]["split"] == "held-out"


def test_load_case_without_split_defaults_to_dev(tmp_path):
    """未标 split 字段的既有用例默认归 dev（向后兼容——不改一字即属 dev）。"""
    path = _write_cases(tmp_path, ['{"input": "你好", "expected_intent": "other"}'])
    cases = load_cases(path, _LABELS)
    assert cases[0]["split"] == "dev"


def test_load_case_with_illegal_split_raises(tmp_path):
    path = _write_cases(
        tmp_path, ['{"input": "你好", "expected_intent": "other", "split": "prod"}']
    )
    with pytest.raises(SystemExit) as exc:
        load_cases(path, _LABELS)
    assert exc.value.code == 2


def test_load_multiturn_case_with_split_still_normalizes_turns(tmp_path):
    """split 字段与既有多轮 turns 归一互不干扰。"""
    path = _write_cases(
        tmp_path,
        [
            '{"turns": ["我想约个按摩", "明天下午2点"], '
            '"expected_intent": "appointment", "split": "held-out"}'
        ],
    )
    cases = load_cases(path, _LABELS)
    assert cases[0]["split"] == "held-out"
    assert cases[0]["turns"] == ["我想约个按摩", "明天下午2点"]


# ── _filter_by_split：默认 dev / --include-heldout / --heldout-only ──────────

def _cases(*splits: str) -> list[dict]:
    return [{"id": i, "split": s} for i, s in enumerate(splits)]


def test_filter_default_keeps_only_dev():
    cases = _cases("dev", "held-out", "dev")
    out = _filter_by_split(cases)
    assert [c["id"] for c in out] == [0, 2]


def test_filter_include_heldout_keeps_all():
    cases = _cases("dev", "held-out", "dev")
    out = _filter_by_split(cases, include_heldout=True)
    assert [c["id"] for c in out] == [0, 1, 2]


def test_filter_heldout_only_keeps_only_heldout():
    cases = _cases("dev", "held-out", "dev", "held-out")
    out = _filter_by_split(cases, heldout_only=True)
    assert [c["id"] for c in out] == [1, 3]


def test_filter_heldout_only_takes_precedence_over_include_heldout():
    """调用方保证互斥，但函数本身对 heldout_only 优先响应（防御性）。"""
    cases = _cases("dev", "held-out")
    out = _filter_by_split(cases, include_heldout=True, heldout_only=True)
    assert [c["id"] for c in out] == [1]


# ── _split_results：dev/held-out 结果分拆，保序，held-out 进不去 dev 侧 ──────

def test_split_results_separates_dev_and_heldout_preserving_order():
    cases = _cases("dev", "held-out", "dev", "held-out")
    results = ["r0", "r1", "r2", "r3"]  # 与 cases 同序
    dev, heldout = _split_results(cases, results)
    assert dev == ["r0", "r2"]
    assert heldout == ["r1", "r3"]


def test_split_results_all_dev_yields_empty_heldout():
    cases = _cases("dev", "dev")
    results = ["r0", "r1"]
    dev, heldout = _split_results(cases, results)
    assert dev == ["r0", "r1"]
    assert heldout == []


def test_split_results_all_heldout_yields_empty_dev():
    """--heldout-only 场景：dev 侧为空——基线/门禁函数据此拿不到任何 dev 数据可用。"""
    cases = _cases("held-out", "held-out")
    results = ["r0", "r1"]
    dev, heldout = _split_results(cases, results)
    assert dev == []
    assert heldout == ["r0", "r1"]


# ── 端到端(纯函数链路)：held-out 物理上进不了基线 ──────────────────────────────

def test_heldout_results_cannot_leak_into_baseline():
    """held-out 用例即便意图全错，也不拉低/影响基线——因为 _split_results 已把它挡在
    build_report/report_to_baseline 之外，dev 侧独立计算。模拟 --include-heldout 场景：
    评估集合含 dev+held-out，但基线只应反映 dev 的真实表现。
    """
    cases = _cases("dev", "dev", "held-out", "held-out")
    results = [
        EvalResult(input="d1", expected_tools=["a"], actual_tools=[{"name": "a", "args": {}}]),
        EvalResult(input="d2", expected_tools=["b"], actual_tools=[{"name": "b", "args": {}}]),
        # held-out 两条全判错——若泄漏进基线会把工具 F1 拉到 50%。
        EvalResult(input="h1", expected_tools=["c"], actual_tools=[{"name": "x", "args": {}}]),
        EvalResult(input="h2", expected_tools=["d"], actual_tools=[{"name": "y", "args": {}}]),
    ]
    dev_results, heldout_results = _split_results(cases, results)
    assert len(dev_results) == 2 and len(heldout_results) == 2

    baseline = report_to_baseline(build_report(dev_results), total_cases=len(dev_results), samples=1)
    # dev 两条全命中 → 工具 F1 100%，不受 held-out 两条判错影响。
    assert baseline["metrics"]["工具调用-F1"]["value"] == 1.0
    assert baseline["meta"]["total_cases"] == 2  # 基线的 total_cases 只计 dev
