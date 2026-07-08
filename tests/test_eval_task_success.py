"""任务成功率指标单测（change evals-task-success-rate）。

纯函数、合成 EvalResult 离线断言：成功 / 执行失败(ok=False) / 终态未调用 / 未标注→N/A /
混合宏平均；并确认该指标**不在门禁**内、不触发非零退出。不触网、不调真实 provider。
"""

from evals.metrics import (
    GATED_METRICS,
    EvalResult,
    build_report,
    compare_to_baseline,
    report_to_baseline,
    task_success_rate,
)


def _r(expected_outcome, outcomes):
    """构造一条标了 expected_outcome、带 actual_tool_outcomes 的用例。"""
    return EvalResult(
        "in", "appointment", actual_intent="appointment",
        expected_outcome=expected_outcome, actual_tool_outcomes=outcomes,
    )


def test_success_when_terminal_tool_called_and_ok():
    r = _r("create_appointment", [
        {"name": "find_technician", "ok": True},
        {"name": "create_appointment", "ok": True},
    ])
    m = task_success_rate([r])
    assert m.value == 1.0
    assert m.numerator == 1 and m.denominator == 1


def test_not_success_when_terminal_tool_failed():
    r = _r("create_appointment", [
        {"name": "find_technician", "ok": True},
        {"name": "create_appointment", "ok": False},  # 调了但执行失败
    ])
    m = task_success_rate([r])
    assert m.value == 0.0
    assert m.denominator == 1


def test_not_success_when_terminal_tool_not_called():
    r = _r("create_appointment", [{"name": "find_technician", "ok": True}])
    m = task_success_rate([r])
    assert m.value == 0.0


def test_success_when_any_same_named_outcome_ok():
    """同名终态多次：任一 ok 即成功（贴合「办成了」语义）。"""
    r = _r("create_appointment", [
        {"name": "create_appointment", "ok": False},
        {"name": "create_appointment", "ok": True},
    ])
    assert task_success_rate([r]).value == 1.0


def test_na_when_no_case_annotated():
    """无用例标 expected_outcome → 显式 N/A，不伪造分母。"""
    r = EvalResult("in", "pay", actual_intent="pay", actual_tool_outcomes=[{"name": "x", "ok": True}])
    m = task_success_rate([r])
    assert m.na is True
    assert m.value is None


def test_na_when_not_captured():
    """标了 expected_outcome 但未真跑捕获(actual_tool_outcomes=None) → 不计入。"""
    r = EvalResult("in", "appointment", expected_outcome="create_appointment", actual_tool_outcomes=None)
    assert task_success_rate([r]).na is True


def test_macro_average_mixed():
    """3 条计入：2 成功 1 失败 → 2/3；未标注的第 4 条不进分母。"""
    rs = [
        _r("create_appointment", [{"name": "create_appointment", "ok": True}]),
        _r("search_knowledge", [{"name": "search_knowledge", "ok": True}]),
        _r("create_appointment", [{"name": "find_technician", "ok": True}]),  # 未达终态
        EvalResult("in", "other", actual_intent="other", actual_tool_outcomes=[]),  # 未标注
    ]
    m = task_success_rate(rs)
    assert m.numerator == 2 and m.denominator == 3
    assert abs(m.value - 2 / 3) < 1e-9


def test_task_success_in_report_but_not_gated():
    """任务成功率进多指标报告，但不在 GATED_METRICS、不触发门禁非零。"""
    assert "任务成功率" not in GATED_METRICS
    rs = [_r("create_appointment", [{"name": "create_appointment", "ok": True}])]
    rep = build_report(rs)
    assert any(m.name == "任务成功率" for m in rep["metrics"])

    # 基线收录任务成功率（作历史参照），但门禁只遍历 GATED_METRICS → 不因它退出非零。
    base = report_to_baseline(rep, total_cases=1, samples=1)
    assert "任务成功率" in base["metrics"]
    # 当前视图给一个「任务成功率」远低于基线的值，门禁仍 PASS（因不在 gated 内）。
    current = {"任务成功率": (0.0, False)}
    gate = compare_to_baseline(current, base, tolerance=0.2)
    assert gate.passed is True
    assert all(v.name != "任务成功率" for v in gate.verdicts)  # 压根不比它
