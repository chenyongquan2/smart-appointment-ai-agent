"""评估用例数据集的 schema 与规模下限自检（change: evals-dataset-scaleup-v2）。

**为什么做成常驻测试而不是一次性脚本**：数据集会被反复编辑（在线回灌、后续扩容），
而它的约束是「靠人肉核对就一定会漏」的那类——漏标一个键、held-out 复用了 dev 原句、
`expected_outcome` 与 `expected_tools` 自相矛盾，这些都不会让运行器报错，只会让指标
悄悄失真。把约束变成断言，任何人改数据集时都会被拦住。

覆盖：字段合法性、单轮/多轮互斥、split 取值、工具名白名单、终态标注不自相矛盾、
每类规模下限、输入无完全重复、held-out 不泄漏。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

CASES_PATH = Path(__file__).resolve().parent.parent / "evals" / "cases.jsonl"

INTENTS = {"appointment", "query", "pay", "statistics", "other"}
TOOLS = {
    "search_knowledge",
    "find_technician",
    "check_availability",
    "create_appointment",
    "get_user_preferences",
}
# 只有这两类存在「业务终态工具」；pay/statistics/other 是负样本（不该调工具），
# 给它们标 expected_outcome 会伪造任务成功率的分母。
INTENTS_WITH_OUTCOME = {"appointment", "query"}

MIN_PER_CATEGORY_DEV = 30
MIN_HELDOUT_TOTAL = 30


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    raw = CASES_PATH.read_text(encoding="utf-8").splitlines()
    out = []
    for lineno, line in enumerate(raw, 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            out.append({"_lineno": lineno, **json.loads(line)})
        except json.JSONDecodeError as exc:  # pragma: no cover - 数据坏了才会走到
            pytest.fail(f"第 {lineno} 行不是合法 JSON: {exc}")
    return out


def label(case: dict) -> str:
    text = case.get("input") or " || ".join(case.get("turns") or [])
    return f"第 {case['_lineno']} 行 {text[:30]!r}"


# --------------------------------------------------------------------------- #
# 字段合法性
# --------------------------------------------------------------------------- #
def test_input_and_turns_are_mutually_exclusive(cases):
    """恰有其一。皆有/皆缺时运行器会报行号退出，但那要等到跑批才暴露。"""
    bad = [
        label(c) for c in cases
        if bool(c.get("input")) == bool(c.get("turns"))
    ]
    assert not bad, f"input 与 turns 必须恰有其一：{bad}"


def test_turns_are_non_empty_strings(cases):
    bad = [
        label(c) for c in cases
        if c.get("turns") and not all(isinstance(t, str) and t.strip() for t in c["turns"])
    ]
    assert not bad, f"turns 必须是非空字符串列表：{bad}"


def test_intents_are_known(cases):
    bad = [f"{label(c)} -> {c.get('expected_intent')!r}" for c in cases
           if c.get("expected_intent") not in INTENTS]
    assert not bad, f"expected_intent 非法：{bad}"


def test_expected_tools_present_and_known(cases):
    missing = [label(c) for c in cases if not isinstance(c.get("expected_tools"), list)]
    assert not missing, f"缺 expected_tools：{missing}"

    unknown = [
        f"{label(c)} -> {t}" for c in cases
        for t in c["expected_tools"] if t not in TOOLS
    ]
    assert not unknown, f"未知工具名：{unknown}"


def test_split_values_are_valid(cases):
    bad = [f"{label(c)} -> {c.get('split')!r}" for c in cases
           if c.get("split", "dev") not in {"dev", "held-out"}]
    assert not bad, f"split 只能是 dev / held-out：{bad}"


# --------------------------------------------------------------------------- #
# 终态标注不自相矛盾
# --------------------------------------------------------------------------- #
def test_outcome_only_on_intents_that_have_one(cases):
    """pay/statistics/other 无业务终态工具，标了就是伪造任务成功率的分母。"""
    bad = [
        f"{label(c)} ({c['expected_intent']})" for c in cases
        if c.get("expected_outcome") and c["expected_intent"] not in INTENTS_WITH_OUTCOME
    ]
    assert not bad, f"这些类不该标 expected_outcome：{bad}"


def test_outcome_is_among_expected_tools(cases):
    """终态工具必须在「预期会调的工具」里——否则用例自己就矛盾，永远不可能成功。"""
    bad = [
        f"{label(c)} outcome={c['expected_outcome']} tools={c['expected_tools']}"
        for c in cases
        if c.get("expected_outcome") and c["expected_outcome"] not in c["expected_tools"]
    ]
    assert not bad, f"expected_outcome 不在 expected_tools 内（自相矛盾）：{bad}"


def test_outcome_is_a_known_tool(cases):
    bad = [f"{label(c)} -> {c['expected_outcome']}" for c in cases
           if c.get("expected_outcome") and c["expected_outcome"] not in TOOLS]
    assert not bad, f"expected_outcome 非法：{bad}"


def test_negative_samples_declare_no_tools(cases):
    """pay/statistics/other 是负样本：测的正是「不该调工具时别乱调」。"""
    bad = [
        f"{label(c)} ({c['expected_intent']}) -> {c['expected_tools']}"
        for c in cases
        if c["expected_intent"] not in INTENTS_WITH_OUTCOME and c["expected_tools"]
    ]
    assert not bad, f"负样本类不该声明期望工具：{bad}"


# --------------------------------------------------------------------------- #
# 规模下限（change evals-dataset-scaleup-v2 的约定）
# --------------------------------------------------------------------------- #
def test_dev_meets_per_category_floor(cases):
    dev = Counter(c["expected_intent"] for c in cases if c.get("split", "dev") == "dev")
    short = {cat: dev.get(cat, 0) for cat in sorted(INTENTS)
             if dev.get(cat, 0) < MIN_PER_CATEGORY_DEV}
    assert not short, f"dev 每类需 ≥{MIN_PER_CATEGORY_DEV} 条，未达标：{short}"


def test_heldout_meets_floor_and_covers_all_intents(cases):
    ho = [c for c in cases if c.get("split") == "held-out"]
    assert len(ho) >= MIN_HELDOUT_TOTAL, \
        f"held-out 需 ≥{MIN_HELDOUT_TOTAL} 条，当前 {len(ho)}"

    per = Counter(c["expected_intent"] for c in ho)
    missing = sorted(INTENTS - set(per))
    assert not missing, f"held-out 缺这些类：{missing}"


# --------------------------------------------------------------------------- #
# 去重与防泄漏
# --------------------------------------------------------------------------- #
def test_no_duplicate_inputs(cases):
    """完全重复只会让某条样本被加权两次，悄悄改变宏平均。（近似重复仍需人工把关。）"""
    texts = [c["input"] for c in cases if c.get("input")]
    dupes = {t: n for t, n in Counter(texts).items() if n > 1}
    assert not dupes, f"输入完全重复：{dupes}"


def test_no_duplicate_turn_sequences(cases):
    seqs = [tuple(c["turns"]) for c in cases if c.get("turns")]
    dupes = {s: n for s, n in Counter(seqs).items() if n > 1}
    assert not dupes, f"多轮序列完全重复：{dupes}"


def test_heldout_does_not_reuse_dev_inputs(cases):
    """held-out 一旦与 dev 同句，过拟合体检就失去意义——它测的是"没见过的说法"。"""
    dev = {c["input"] for c in cases if c.get("input") and c.get("split", "dev") == "dev"}
    ho = {c["input"] for c in cases if c.get("input") and c.get("split") == "held-out"}
    leaked = dev & ho
    assert not leaked, f"held-out 复用了 dev 原句（泄漏）：{leaked}"


# --------------------------------------------------------------------------- #
# 一条汇总用例：跑失败时把当前分布打出来，便于定位
# --------------------------------------------------------------------------- #
def test_distribution_summary_is_sane(cases):
    dev = Counter(c["expected_intent"] for c in cases if c.get("split", "dev") == "dev")
    ho = Counter(c["expected_intent"] for c in cases if c.get("split") == "held-out")
    multiturn = sum(1 for c in cases if c.get("turns"))
    with_outcome = sum(1 for c in cases if c.get("expected_outcome"))

    summary = (
        f"总 {len(cases)} 条 | dev {sum(dev.values())} {dict(dev)} | "
        f"held-out {sum(ho.values())} {dict(ho)} | 多轮 {multiturn} | 带终态 {with_outcome}"
    )
    assert sum(dev.values()) > 0 and sum(ho.values()) > 0, summary
    # 多轮样本是轨迹级评估的唯一来源，掉到 0 说明数据集被改坏了
    assert multiturn > 0, f"多轮用例不能为 0：{summary}"
