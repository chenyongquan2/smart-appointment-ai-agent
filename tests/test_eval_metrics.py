"""评估多指标计算单测（Phase 6 评估闭环）。

纯函数、用合成 EvalResult 离线断言：工具调用正确率 / 槽位完整率 / 端到端延迟，
以及缺数据时显式 N/A 的逻辑。不触网、不调用真实 provider。
（change retire-legacy-intent-classifier）意图分类准确率已随旧分类器退役。
"""

from evals.metrics import (
    EvalResult,
    build_report,
    format_report,
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


def test_tool_call_exact_match_and_na():
    # 完全匹配率：集合全等、全有或全无、顺序无关。
    results = [
        EvalResult("a",
                   expected_tools=["find_technician", "create_appointment"],
                   actual_tools=[_tool("create_appointment"), _tool("find_technician")]),  # 顺序不同仍算对
        EvalResult("b",
                   expected_tools=["check_availability"],
                   actual_tools=[_tool("find_technician")]),  # 不同 → 算错
    ]
    m = tool_call_exact_match(results)
    assert (m.numerator, m.denominator) == (1, 2)
    # 全部缺 actual_tools → N/A，不伪造分母。
    na = tool_call_exact_match([EvalResult("c", expected_tools=["x"])])
    assert na.na and na.value is None and na.note


def test_tool_call_partial_credit_recall_precision_f1():
    # 期望 3 个、只调到 1 个：召回 1/3，而非完全匹配的 0（治"全有或全无"的误导）。
    results = [
        EvalResult("a",
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
        EvalResult("a", expected_tools=["x", "y"],
                   actual_tools=[_tool("x"), _tool("y")]),       # recall 1.0
        EvalResult("b", expected_tools=["m", "n"],
                   actual_tools=[_tool("m")]),                    # recall 0.5
    ]
    recall, _, _ = tool_call_recall_precision_f1(results)
    assert recall.value == 0.75  # (1.0 + 0.5) / 2，每条等权

    na, _, _ = tool_call_recall_precision_f1([EvalResult("c", expected_tools=["x"])])
    assert na.na and na.value is None


def test_tool_call_param_level_only_compares_annotated_keys():
    # 参数级：只比标注的键，actual 多出的键忽略。
    results = [
        EvalResult("a", expected_tools=["find_technician"],
                   actual_tools=[_tool("find_technician", gender="male", project="推拿")],
                   expected_tool_args={"find_technician": {"gender": "male"}}),  # 只标 gender
    ]
    m = tool_call_param_f1(results)
    assert not m.na and m.value == 1.0  # gender 匹配，多出的 project 不影响

    # 标注的键 actual 值不符 → 不命中 → F1 = 0。
    bad = [
        EvalResult("a", expected_tools=["find_technician"],
                   actual_tools=[_tool("find_technician", gender="female")],
                   expected_tool_args={"find_technician": {"gender": "male"}}),
    ]
    assert tool_call_param_f1(bad).value == 0.0

    # 未标 expected_tool_args → N/A，不伪造分母。
    na = tool_call_param_f1([EvalResult("b", expected_tools=["x"],
                                        actual_tools=[_tool("x")])])
    assert na.na and na.value is None


def test_tool_call_param_normalization():
    # 归一化：duration 60(int) ≡ "60"(str)；gender 大小写不敏感。
    results = [
        EvalResult("a", expected_tools=["create_appointment"],
                   actual_tools=[_tool("create_appointment", duration="60", gender="Male")],
                   expected_tool_args={"create_appointment": {"duration": 60, "gender": "male"}}),
    ]
    assert tool_call_param_f1(results).value == 1.0


def test_tool_call_sequence_subsequence_and_na():
    # 子序列匹配：容忍多调（B 夹在中间），逆序判错。
    ok = [
        EvalResult("a", expected_tools=["A", "C"],
                   actual_tools=[_tool("A"), _tool("B"), _tool("C")]),  # A 在 C 前 → 对
    ]
    assert tool_call_sequence_correctness(ok).value == 1.0

    rev = [
        EvalResult("a", expected_tools=["A", "B"],
                   actual_tools=[_tool("B"), _tool("A")]),  # 逆序 → 错
    ]
    assert tool_call_sequence_correctness(rev).value == 0.0

    na = tool_call_sequence_correctness([EvalResult("c", expected_tools=["x"])])
    assert na.na and na.value is None


def test_slot_completeness_presence_based_partial_and_na():
    # 存在性口径（change evals-wire-slot-completeness D8）：命中 = 期望键存在于 actual，不比值。
    results = [
        EvalResult(
            "a",
            # 期望 2 个键；actual 只抽到 project（time 缺）→ 命中 1/2。
            expected_slots={"project": "肩颈", "start_time": "14:00"},
            actual_slots={"project": "肩颈"},
        ),
    ]
    m = slot_completeness(results)
    assert m.value == 0.5

    # 值不同但键存在仍算命中（存在性、不比值）：project 值不等但都在 → 2/2 = 1.0。
    hit_by_presence = slot_completeness([
        EvalResult(
            "c",
            expected_slots={"project": "肩颈", "gender": "female"},
            actual_slots={"project": "全身", "gender": "男"},  # 值都不等，但键都在
        ),
    ])
    assert hit_by_presence.value == 1.0

    # 无 expected_slots → N/A。
    na = slot_completeness([EvalResult("b")])
    assert na.na


def test_latency_summary():
    results = [
        EvalResult("a", latency_s=0.1),
        EvalResult("b", latency_s=0.3),
        EvalResult("c", latency_s=0.2),
    ]
    m = latency_summary(results)
    assert m.extra["max_s"] == 0.3
    assert abs(m.extra["avg_s"] - 0.2) < 1e-9
    assert m.extra["p50_s"] == 0.2

    assert latency_summary([EvalResult("x")]).na


def test_build_and_format_report_marks_na():
    results = [
        EvalResult(
            "约一下",
            expected_tools=["find_technician"], actual_tools=None,  # 工具 N/A
            latency_s=0.05,
        ),
        EvalResult("查价格", latency_s=0.07),
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
    assert by_name["端到端延迟"].na is False
    # 意图分类准确率已退役，报告不应再出现（change retire-legacy-intent-classifier）。
    assert "意图分类准确率" not in by_name
    assert "errors" not in report

    # 文本层：N/A 标注、延迟摘要均出现（用稳定子串）。
    assert "N/A" in text
    assert "avg" in text and "max" in text
    assert report["total"] == 2
