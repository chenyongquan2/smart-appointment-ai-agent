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
    tool_call_exact_match,
    tool_call_param_f1,
    tool_call_recall_precision_f1,
    tool_call_sequence_correctness,
)


def _tool(name, **args):
    """构造一个采全形态的工具调用 {name, args}。"""
    return {"name": name, "args": dict(args)}


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


def test_tool_call_exact_match_and_na():
    # 完全匹配率：集合全等、全有或全无、顺序无关。
    results = [
        EvalResult("a", "appointment",
                   expected_tools=["find_technician", "create_appointment"],
                   actual_tools=[_tool("create_appointment"), _tool("find_technician")]),  # 顺序不同仍算对
        EvalResult("b", "appointment",
                   expected_tools=["check_availability"],
                   actual_tools=[_tool("find_technician")]),  # 不同 → 算错
    ]
    m = tool_call_exact_match(results)
    assert (m.numerator, m.denominator) == (1, 2)
    # 全部缺 actual_tools → N/A，不伪造分母。
    na = tool_call_exact_match([EvalResult("c", "appointment", expected_tools=["x"])])
    assert na.na and na.value is None and na.note


def test_tool_call_partial_credit_recall_precision_f1():
    # 期望 3 个、只调到 1 个：召回 1/3，而非完全匹配的 0（治"全有或全无"的误导）。
    results = [
        EvalResult("a", "appointment",
                   expected_tools=["find_technician", "check_availability", "create_appointment"],
                   actual_tools=[_tool("find_technician")]),
    ]
    recall, precision, f1 = tool_call_recall_precision_f1(results)
    assert recall.name == "工具调用-召回率" and abs(recall.value - 1 / 3) < 1e-9
    assert precision.name == "工具调用-精确率" and precision.value == 1.0  # 调的那个是对的
    assert f1.name == "工具调用-F1" and abs(f1.value - 0.5) < 1e-9  # 2*1*(1/3)/(1+1/3)
    # 而完全匹配率对同一条记 0。
    assert tool_call_exact_match(results).value == 0.0


def test_tool_call_partial_credit_macro_average():
    # 宏平均：每条用例等权（不被工具多的用例带偏）。
    results = [
        EvalResult("a", "appointment", expected_tools=["x", "y"],
                   actual_tools=[_tool("x"), _tool("y")]),       # recall 1.0
        EvalResult("b", "appointment", expected_tools=["m", "n"],
                   actual_tools=[_tool("m")]),                    # recall 0.5
    ]
    recall, _, _ = tool_call_recall_precision_f1(results)
    assert recall.value == 0.75  # (1.0 + 0.5) / 2，每条等权

    na, _, _ = tool_call_recall_precision_f1([EvalResult("c", "appointment", expected_tools=["x"])])
    assert na.na and na.value is None


def test_tool_call_param_level_only_compares_annotated_keys():
    # 参数级：只比标注的键，actual 多出的键忽略。
    results = [
        EvalResult("a", "appointment", expected_tools=["find_technician"],
                   actual_tools=[_tool("find_technician", gender="male", project="推拿")],
                   expected_tool_args={"find_technician": {"gender": "male"}}),  # 只标 gender
    ]
    m = tool_call_param_f1(results)
    assert not m.na and m.value == 1.0  # gender 匹配，多出的 project 不影响

    # 标注的键 actual 值不符 → 不命中 → F1 = 0。
    bad = [
        EvalResult("a", "appointment", expected_tools=["find_technician"],
                   actual_tools=[_tool("find_technician", gender="female")],
                   expected_tool_args={"find_technician": {"gender": "male"}}),
    ]
    assert tool_call_param_f1(bad).value == 0.0

    # 未标 expected_tool_args → N/A，不伪造分母。
    na = tool_call_param_f1([EvalResult("b", "appointment", expected_tools=["x"],
                                        actual_tools=[_tool("x")])])
    assert na.na and na.value is None


def test_tool_call_param_normalization():
    # 归一化：duration 60(int) ≡ "60"(str)；gender 大小写不敏感。
    results = [
        EvalResult("a", "appointment", expected_tools=["create_appointment"],
                   actual_tools=[_tool("create_appointment", duration="60", gender="Male")],
                   expected_tool_args={"create_appointment": {"duration": 60, "gender": "male"}}),
    ]
    assert tool_call_param_f1(results).value == 1.0


def test_tool_call_sequence_subsequence_and_na():
    # 子序列匹配：容忍多调（B 夹在中间），逆序判错。
    ok = [
        EvalResult("a", "appointment", expected_tools=["A", "C"],
                   actual_tools=[_tool("A"), _tool("B"), _tool("C")]),  # A 在 C 前 → 对
    ]
    assert tool_call_sequence_correctness(ok).value == 1.0

    rev = [
        EvalResult("a", "appointment", expected_tools=["A", "B"],
                   actual_tools=[_tool("B"), _tool("A")]),  # 逆序 → 错
    ]
    assert tool_call_sequence_correctness(rev).value == 0.0

    na = tool_call_sequence_correctness([EvalResult("c", "appointment", expected_tools=["x"])])
    assert na.na and na.value is None


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
    # 工具调用各分档在无 actual_tools 时均 N/A（不伪造分母）。
    assert by_name["工具调用-召回率"].na is True
    assert by_name["工具调用-完全匹配率"].na is True
    assert by_name["工具调用-参数级F1"].na is True
    assert by_name["工具调用-序列正确率"].na is True
    assert by_name["槽位抽取完整率"].na is True
    assert by_name["意图分类准确率"].value == 0.5
    assert by_name["端到端延迟"].na is False
    assert len(report["errors"]) == 1

    # 文本层：N/A 标注、延迟摘要、判错明细均出现（用稳定子串）。
    assert "N/A" in text
    assert "avg" in text and "max" in text
    assert "约一下" in text and "期望: appointment" in text
    assert "50.0%" in text
