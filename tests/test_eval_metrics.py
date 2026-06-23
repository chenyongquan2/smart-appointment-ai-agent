"""评估多指标计算单测（Phase 6 评估闭环）。

纯函数、用合成 EvalResult 离线断言：意图准确率 / 工具调用正确率 / 槽位完整率 /
端到端延迟，以及缺数据时显式 N/A 的逻辑。不触网、不调用真实 provider。
"""

from evals.metrics import (
    EvalResult,
    build_report,
    format_report,
    intent_accuracy,
    latency_summary,
    slot_completeness,
    tool_call_correctness,
)


def test_intent_accuracy_counts_only_classified():
    results = [
        EvalResult("a", "query", actual_intent="query"),
        EvalResult("b", "pay", actual_intent="appointment"),
        EvalResult("c", "other", actual_intent=None),  # 未分类，不计入分母
    ]
    m = intent_accuracy(results)
    assert (m.numerator, m.denominator) == (1, 2)
    assert m.value == 0.5
    assert not m.na


def test_tool_call_correctness_set_compare_and_na():
    # 含 expected+actual：顺序无关的集合比较。
    results = [
        EvalResult(
            "a", "appointment",
            expected_tools=["find_technician", "create_appointment"],
            # actual_tools 采全为 {name, args} 列表；指标只比名字集合，故顺序不同仍算对。
            actual_tools=[
                {"name": "create_appointment", "args": {}},
                {"name": "find_technician", "args": {}},
            ],
        ),
        EvalResult(
            "b", "appointment",
            expected_tools=["check_availability"],
            actual_tools=[{"name": "find_technician", "args": {}}],  # 不同 → 算错
        ),
    ]
    m = tool_call_correctness(results)
    assert (m.numerator, m.denominator) == (1, 2)

    # 全部缺 actual_tools → N/A，不伪造分母。
    na = tool_call_correctness([EvalResult("c", "appointment", expected_tools=["x"])])
    assert na.na and na.value is None and na.note


def test_slot_completeness_partial_and_na():
    results = [
        EvalResult(
            "a", "appointment",
            expected_slots={"project": "肩颈", "time": "14:00"},
            actual_slots={"project": "肩颈", "time": "15:00"},  # 命中 1/2
        ),
    ]
    m = slot_completeness(results)
    assert m.value == 0.5

    # 无 expected_slots → N/A。
    na = slot_completeness([EvalResult("b", "query")])
    assert na.na


def test_latency_summary():
    results = [
        EvalResult("a", "query", latency_s=0.1),
        EvalResult("b", "query", latency_s=0.3),
        EvalResult("c", "query", latency_s=0.2),
    ]
    m = latency_summary(results)
    assert m.extra["max_s"] == 0.3
    assert abs(m.extra["avg_s"] - 0.2) < 1e-9
    assert m.extra["p50_s"] == 0.2

    assert latency_summary([EvalResult("x", "query")]).na


def test_build_and_format_report_marks_na_and_lists_errors():
    results = [
        EvalResult(
            "约一下", "appointment", actual_intent="query",  # 判错
            expected_tools=["find_technician"], actual_tools=None,  # 工具 N/A
            latency_s=0.05,
        ),
        EvalResult("查价格", "query", actual_intent="query", latency_s=0.07),
    ]
    report = build_report(results)
    text = format_report(report)

    # 指标对象层断言（不受文本对齐空格影响）。
    by_name = {m.name: m for m in report["metrics"]}
    assert by_name["工具调用正确率"].na is True
    assert by_name["槽位抽取完整率"].na is True
    assert by_name["意图分类准确率"].value == 0.5
    assert by_name["端到端延迟"].na is False
    assert len(report["errors"]) == 1

    # 文本层：N/A 标注、延迟摘要、判错明细均出现（用稳定子串）。
    assert "N/A" in text
    assert "avg" in text and "max" in text
    assert "约一下" in text and "期望: appointment" in text
    assert "50.0%" in text
