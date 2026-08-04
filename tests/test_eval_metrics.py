"""评估多指标计算单测（Phase 6 评估闭环）。

纯函数、用合成 EvalResult 离线断言：工具调用正确率 / 槽位完整率 / 端到端延迟，
以及缺数据时显式 N/A 的逻辑。不触网、不调用真实 provider。
（change retire-legacy-intent-classifier）意图分类准确率已随旧分类器退役。
"""

import pytest

from evals.metrics import (
    EvalResult,
    F1_NEGATIVE,
    F1_POSITIVE,
    GATED_METRICS,
    POLARITY_METRICS,
    compare_to_baseline,
    tool_call_f1_by_polarity,
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


# --------------------------------------------------------------------------- #
# 工具调用 F1 的正/负样本分档（change: evals-f1-polarity-breakdown）
#
# 为什么要分：宏平均对空期望集给免费满分（`if expected else 1.0`），故总 F1 是
# **按正/负构成比例加权的平均数**，不是能力指标。实测过一次——负样本占比 37%→58%
# 时 F1 从 56.2% 机械升到 78.5%，而同期难例占比反从 65% 掉到 38%，能力毫无变化。
# --------------------------------------------------------------------------- #
def _pos(name="a"):
    """正样本：期望非空。命中 1/2 → 召回 0.5、精确 1.0 → **F1 = 2/3**（不是 0.5）。"""
    return EvalResult(name, expected_tools=["find_technician", "create_appointment"],
                      actual_tools=[_tool("find_technician")])


def _neg(name="n", clean=True):
    """负样本：期望为空。clean=不乱调 → 免费满分 1.0；否则乱调 → 0.0。"""
    return EvalResult(name, expected_tools=[],
                      actual_tools=[] if clean else [_tool("search_knowledge")])


def test_polarity_split_reports_each_bucket_with_share():
    """★ 分档要带 n 与占比——只给两个 F1 值仍看不出总数为何是这个数。"""
    results = [_pos("p1"), _pos("p2"), _neg("n1"), _neg("n2"), _neg("n3")]
    by_name = {m.name: m for m in tool_call_f1_by_polarity(results)}

    pos, neg = by_name[F1_POSITIVE], by_name[F1_NEGATIVE]
    assert pos.value == pytest.approx(2 / 3) and pos.denominator == 2
    assert neg.value == pytest.approx(1.0) and neg.denominator == 3
    assert pos.extra["share"] == pytest.approx(2 / 5)
    assert neg.extra["share"] == pytest.approx(3 / 5)


def test_polarity_split_is_weight_consistent():
    """★ 核心主张：总 F1 == 正档×正占比 + 负档×负占比。

    宏平均的定义使这条恒成立。**它红了就说明分档算错了**——也说明"总 F1 是加权
    平均"这个要传达的结论失去了依据。
    """
    results = [_pos("p1"), _pos("p2"), _neg("n1"), _neg("n2", clean=False), _neg("n3")]
    total = {m.name: m for m in tool_call_recall_precision_f1(results)}["工具调用-F1"]
    by_name = {m.name: m for m in tool_call_f1_by_polarity(results)}
    pos, neg = by_name[F1_POSITIVE], by_name[F1_NEGATIVE]

    recombined = pos.value * pos.extra["share"] + neg.value * neg.extra["share"]
    assert total.value == pytest.approx(recombined)


def test_polarity_split_keys_on_expected_tools_not_intent():
    """★ 判据是 expected_tools 空/非空，**不是意图类别**（design D1）。

    意图是域绑定的——oncall 没有 pay/statistics/other。按 intent 切的代码换域即失效，
    而免费满分的入口恰恰就是"期望集为空"这件事本身。
    """
    # 一条"咨询类"用例，但标注了期望工具 → 必须落在正样本档。
    consult_with_tools = EvalResult("问价", expected_tools=["search_knowledge"],
                                    actual_tools=[_tool("search_knowledge")])
    by_name = {m.name: m for m in tool_call_f1_by_polarity([consult_with_tools, _neg()])}

    assert by_name[F1_POSITIVE].denominator == 1
    assert by_name[F1_NEGATIVE].denominator == 1


def test_empty_bucket_is_na_not_zero():
    """★ 某档无样本 → N/A，**不记 0**（design D6）。

    0 会被读成"这档全错"，与"没有样本"是完全相反的意思。
    """
    by_name = {m.name: m for m in tool_call_f1_by_polarity([_pos(), _pos("p2")])}

    assert by_name[F1_NEGATIVE].na is True
    assert by_name[F1_NEGATIVE].value is None
    assert by_name[F1_NEGATIVE].note
    assert by_name[F1_POSITIVE].na is False


def test_polarity_na_when_no_tool_capture():
    """没端到端跑 loop（actual_tools 全 None）→ 两档一并 N/A，与总 F1 一致。"""
    by_name = {m.name: m for m in
               tool_call_f1_by_polarity([EvalResult("x", expected_tools=["a"])])}

    assert by_name[F1_POSITIVE].na and by_name[F1_NEGATIVE].na


def test_polarity_metrics_are_not_gated():
    """★ 分档 MUST NOT 进门禁（design D2）。

    进了就要重定基线，而重定基线是「预约域评测冻结」明令禁止的；且负样本 F1 恒
    ~100%、方差极小，守它是个假门禁。没有这条测试，日后"既然算出来了不如守上"
    是很自然的动作。
    """
    assert set(GATED_METRICS).isdisjoint(POLARITY_METRICS)


def test_polarity_does_not_change_gate_verdicts():
    """★ 引入分档后门禁裁决**逐位不变**——本变更只增加可见度，不改任何判定。"""
    baseline = {"metrics": {"工具调用-F1": {"value": 0.70, "is_latency": False}}}
    current = {"工具调用-F1": (0.69, False),
               F1_POSITIVE: (0.10, False),      # 分档值再难看也不该影响裁决
               F1_NEGATIVE: (1.00, False)}

    report = compare_to_baseline(current, baseline, tolerance=0.05)

    assert report.passed is True
    assert [v.name for v in report.verdicts] == ["工具调用-F1"], "分档不该出现在裁决里"
    assert report.guarded_count == 1


def test_report_renders_polarity_as_one_group():
    """分档在报告里是**一组三行**（缩进 + 树线），不是散落的两个新指标。"""
    text = format_report(build_report([_pos(), _neg()]))

    assert "├ 正样本" in text and "└ 负样本" in text
    assert "占 50%" in text, "占比必须打出来——它是加权关系的全部依据"


def test_polarity_survives_multisample_aggregation_with_share():
    """★ 多采样视图必须同样带出分档**和占比**。

    `--samples 3` 才是推荐跑法；占比要是只在单采样视图有，本变更的主张在主视图上
    就不成立了（design D3）。这条是 tasks 2.3 要求"跑一遍确认而不是假定"的那次确认。
    """
    from evals.metrics import aggregate_runs, format_multisample_report

    rows = [_pos("p1"), _pos("p2"), _neg("n1"), _neg("n2")]
    agg = aggregate_runs([build_report(rows), build_report(rows), build_report(rows)])
    by_name = {a.name: a for a in agg}

    pos = by_name[F1_POSITIVE]
    assert pos.na is False
    assert pos.mean == pytest.approx(2 / 3)
    assert pos.n == 3                       # 三次跑都纳入
    assert pos.share == pytest.approx(0.5)  # 占比一路带到聚合层

    text = format_multisample_report(agg, 3, len(rows))
    assert "├ 正样本" in text and "└ 负样本" in text
    assert "占 50%" in text
