"""领域包的评估标注口径声明（change: oncall-evals-bootstrap）。

守两件事：

1. **结构性校验在装载那一刻就炸**——坏声明不能表现为「跑到一半指标莫名 N/A」。
   尤其是空 `gated_metrics`：门禁一项不守却返回 0，是最坏的那种「看起来通过了」。
2. **预约域的三项与重构前的全局硬编码常量等值**——这是那次去域耦合的**等价性锚点**，
   它绿着才敢说「预约域行为不变、无需重定基线」。这条靠肉眼比对守不住，靠测试才行。
"""

from __future__ import annotations

import pytest

from domains import EvalProfile, load_domain


# ── 结构性校验 ──────────────────────────────────────────────────────────────

def test_empty_gated_metrics_rejected():
    """「一个都不守」等于没有门禁，必须显式失败而非默许。"""
    with pytest.raises(ValueError, match="gated_metrics"):
        EvalProfile(labels=frozenset({"a"}), gated_metrics=(), tolerance=0.1)


def test_empty_labels_rejected():
    """没有标签就没有「每类不少于 N 条」的覆盖约束，用例集会长偏。"""
    with pytest.raises(ValueError, match="labels"):
        EvalProfile(labels=frozenset(), gated_metrics=("工具调用-F1",), tolerance=0.1)


def test_duplicate_gated_metrics_rejected():
    with pytest.raises(ValueError, match="重复"):
        EvalProfile(
            labels=frozenset({"a"}),
            gated_metrics=("工具调用-F1", "工具调用-F1"),
            tolerance=0.1,
        )


def test_slot_key_map_defaults_to_empty_and_means_not_measured():
    """空映射是**显式声明**「本域不度量槽位完整率」，不是「忘了配」。"""
    profile = EvalProfile(labels=frozenset({"a"}), gated_metrics=("工具调用-F1",), tolerance=0.1)

    assert profile.slot_key_map == {}
    assert profile.measures_slots is False


def test_slot_key_map_is_read_only_after_construction():
    """frozen 只冻结字段绑定、不深冻内容；包只读视图兑现「装载后没人能改口径」。"""
    source = {"start_time": "start_time"}
    profile = EvalProfile(
        labels=frozenset({"a"}), gated_metrics=("工具调用-F1",), tolerance=0.1,
        slot_key_map=source
    )

    with pytest.raises(TypeError):
        profile.slot_key_map["project"] = "project"  # type: ignore[index]

    source["project"] = "project"  # 改原 dict 也不该影响已装载的口径
    assert "project" not in profile.slot_key_map


# ── 两域的实际声明 ──────────────────────────────────────────────────────────

def test_appointment_profile_matches_pre_refactor_constants():
    """等价性锚点：预约域三项 == 重构前 evals/ 里的全局硬编码值。

    这三个字面量是**故意写死**在测试里的（不从被测代码取），否则它就只是在自我印证。
    """
    profile = load_domain("appointment").eval_profile

    assert profile.labels == frozenset(
        {"appointment", "query", "pay", "statistics", "other"}
    )
    assert profile.gated_metrics == ("工具调用-F1", "槽位抽取完整率")
    assert profile.tolerance == 0.30  # 照抄重构前的全局默认值 → 门禁判定行为等价
    assert dict(profile.slot_key_map) == {
        "start_time": "start_time",
        "duration": "duration",
        "project": "project",
        "preference": "preference",
        "gender": "gender",
        "technician_name": "technician",
    }
    assert profile.measures_slots is True


def test_oncall_profile_gates_param_f1_not_slots():
    """值守域第二道门禁是参数级 F1；槽位完整率按设计不度量、不得进门禁。

    理由见 design D3：本域判别性入参几乎全是必填项/枚举，存在性口径下恒命中，
    槽位完整率会退化成工具 F1 的影子——两项守同一个信号等于第二道形同虚设。
    """
    profile = load_domain("oncall").eval_profile

    assert profile.gated_metrics == ("工具调用-F1", "工具调用-参数级F1")
    assert profile.tolerance == 0.10  # 实测最差半宽 1.1pp；比预约域紧 3 倍
    assert "槽位抽取完整率" not in profile.gated_metrics
    assert profile.measures_slots is False
    assert profile.labels == frozenset(
        {"log_triage", "code_lookup", "docs_lookup", "reference_lookup", "other"}
    )


# ── 机制侧读声明（去域耦合的行为验收） ──────────────────────────────────────

def test_gate_guards_exactly_what_the_domain_declares():
    """门禁遍历的是**域声明**的那几项——此前是全局常量，装上别的域会静默少守一项。"""
    from evals.metrics import compare_to_baseline

    baseline = {"metrics": {
        "工具调用-F1": {"value": 0.70, "is_latency": False},
        "工具调用-参数级F1": {"value": 0.60, "is_latency": False},
        "槽位抽取完整率": {"value": 0.90, "is_latency": False},
    }}
    # 槽位暴跌，但 oncall 不守它 → 不该进裁决、不该判失败。
    current = {
        "工具调用-F1": (0.69, False),
        "工具调用-参数级F1": (0.59, False),
        "槽位抽取完整率": (0.05, False),
    }
    gated = load_domain("oncall").eval_profile.gated_metrics

    report = compare_to_baseline(current, baseline, tolerance=0.05, gated=gated)

    assert report.passed is True
    assert [v.name for v in report.verdicts] == ["工具调用-F1", "工具调用-参数级F1"]
    assert report.guarded_count == 2


def test_validate_rejects_typo_and_ungatable_metrics():
    """拼错的指标名不能静默跳过——静默跳过等于门禁少守一项而没人知道。"""
    from evals.metrics import validate_gated_metrics

    known = {"工具调用-F1", "工具调用-参数级F1", "端到端延迟", "回复质量通过率"}

    validate_gated_metrics(("工具调用-F1", "工具调用-参数级F1"), known)  # 合法：不抛

    with pytest.raises(ValueError, match="不存在的指标名"):
        validate_gated_metrics(("工具调用-Fl",), known)  # 小写 L 冒充 1

    with pytest.raises(ValueError, match="不得守"):
        validate_gated_metrics(("端到端延迟",), known)

    with pytest.raises(ValueError, match="不得守"):
        validate_gated_metrics(("回复质量通过率",), known)


def test_empty_slot_map_yields_distinct_na_note():
    """「本域不度量」与「本次未捕获」是两回事，note 必须区分开。"""
    from evals.metrics import slot_completeness, slots_from_tool_calls

    not_measured = slot_completeness([], measured=False)
    assert not_measured.na is True
    assert "本域不度量" in (not_measured.note or "")

    no_capture = slot_completeness([], measured=True)
    assert no_capture.na is True
    assert "本域不度量" not in (no_capture.note or "")

    # 空映射下即便真跑采到了工具调用，也不还原槽位（恒 N/A，是设计不是抖动）。
    calls = [{"name": "vlog_query", "args": {"env": "prod"}}]
    assert slots_from_tool_calls(calls, {}) is None


def test_two_domains_declare_disjoint_labels():
    """两域标签毫无关系，MUST NOT 混用或互相比较——这条把误用挡在编码期。"""
    appointment = load_domain("appointment").eval_profile.labels
    oncall = load_domain("oncall").eval_profile.labels

    assert appointment & oncall == {"other"}, "除 other 外不应有任何同名标签"


# ── 容差随域声明（change gate-tolerance-per-domain） ─────────────────────────

@pytest.mark.parametrize("bad", [1.0, 1.5, -0.1])
def test_tolerance_out_of_range_rejected(bad):
    """≥1.0 的比率容差等于门禁永不判回归；负数无意义。"""
    with pytest.raises(ValueError, match="tolerance"):
        EvalProfile(labels=frozenset({"a"}), gated_metrics=("工具调用-F1",), tolerance=bad)


def test_zero_tolerance_is_legal():
    """0.0 = 零容忍，任何下降都算回归——合法且有意义的严格模式，不该被拦。"""
    profile = EvalProfile(
        labels=frozenset({"a"}), gated_metrics=("工具调用-F1",), tolerance=0.0
    )

    assert profile.tolerance == 0.0


def test_tolerance_has_no_default():
    """**刻意无缺省**：任何缺省都是「按某个域校准的数」，正是本字段要消灭的东西。"""
    with pytest.raises(TypeError):
        EvalProfile(labels=frozenset({"a"}), gated_metrics=("工具调用-F1",))  # type: ignore[call-arg]


def test_resolve_tolerance_prefers_explicit_over_domain_declaration():
    """不传用域声明；显式传则覆盖（排障与临时放宽必须可用）。

    比的是 run_evals 自己装载的那个 profile，**不是**现调一次 `load_domain()`——后者读
    的是当前环境变量，而 `_EVAL_PROFILE` 在 import 那一刻就定死了。全量跑时若有别的
    测试正 monkeypatch 着 `AGENT_DOMAIN`，两者会指向不同的域（实测踩到过）。
    """
    from evals import run_evals

    declared, source = run_evals._resolve_tolerance(None)
    assert declared == run_evals._EVAL_PROFILE.tolerance
    assert run_evals._DOMAIN.name in source
    assert "声明" in source

    override, source = run_evals._resolve_tolerance(0.05)
    assert override == 0.05
    assert "覆盖" in source


def test_gate_report_shows_tolerance_source():
    """容差不再是命令里看得见的字面量，来源必须与判定结论同处输出。"""
    from evals.metrics import compare_to_baseline, format_gate_report

    baseline = {"metrics": {"工具调用-F1": {"value": 0.70, "is_latency": False}}}
    report = compare_to_baseline(
        {"工具调用-F1": (0.69, False)}, baseline, 0.10, gated=("工具调用-F1",)
    )

    assert "来自域 'oncall' 声明" in format_gate_report(report, "来自域 'oncall' 声明")
    assert "命令行覆盖" in format_gate_report(report, "命令行覆盖")
    assert "容差 0.100" in format_gate_report(report)  # 不给来源也不该崩
