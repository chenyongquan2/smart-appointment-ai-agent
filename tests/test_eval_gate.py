"""回归门禁纯函数单测（改造 6）。

合成报告/基线离线断言：基线序列化（收全部非 N/A、跳过 N/A、记 is_latency）、
门禁比对（被守指标回归/容差内/非门禁指标不阻断）、缺数据语义（skipped/new）、
以及渲染含基线/当前/差值 + 「实守 N 项」末行。不触网、不调真实 provider。
"""

from evals.metrics import (
    AggregatedMetric,
    GATED_METRICS,
    Metric,
    aggregated_to_baseline,
    compare_to_baseline,
    format_gate_report,
    report_to_baseline,
)


def _report(*metrics: Metric) -> dict:
    """包成 build_report 形态（门禁序列化只读 metrics 字段）。"""
    return {"metrics": list(metrics), "errors": [], "total": 0}


# ── 基线序列化 ──────────────────────────────────────────────────────────────

def test_report_to_baseline_records_non_na_and_skips_na():
    report = _report(
        Metric("意图分类准确率", value=0.9, numerator=9, denominator=10),
        Metric("工具调用-F1", value=0.7, denominator=10),
        Metric("端到端延迟", value=1.234, denominator=10, extra={"avg_s": 1.234}),
        Metric("槽位抽取完整率", na=True, note="无槽位"),  # N/A → 不写入
    )
    base = report_to_baseline(report, total_cases=20, samples=3)
    assert base["schema_version"] == 1
    assert base["meta"] == {"total_cases": 20, "samples": 3}
    assert set(base["metrics"]) == {"意图分类准确率", "工具调用-F1", "端到端延迟"}
    # 延迟项标 is_latency=True，比率项 False。
    assert base["metrics"]["端到端延迟"]["is_latency"] is True
    assert base["metrics"]["意图分类准确率"] == {"value": 0.9, "is_latency": False}
    # N/A 的槽位不出现。
    assert "槽位抽取完整率" not in base["metrics"]


def test_aggregated_to_baseline_uses_mean_and_skips_na():
    aggregated = [
        AggregatedMetric(name="意图分类准确率", mean=0.85, half_width=0.02, n=3),
        AggregatedMetric(name="端到端延迟", mean=1.5, half_width=0.1, n=3, is_latency=True),
        AggregatedMetric(name="工具调用-F1", na=True),  # N/A → 跳过
    ]
    base = aggregated_to_baseline(aggregated, total_cases=20, samples=3)
    assert base["metrics"]["意图分类准确率"]["value"] == 0.85
    assert base["metrics"]["端到端延迟"]["is_latency"] is True
    assert "工具调用-F1" not in base["metrics"]


# ── 门禁比对 ────────────────────────────────────────────────────────────────

def _baseline(**metrics) -> dict:
    """{name: (value, is_latency)} → 基线 dict。"""
    return {
        "schema_version": 1,
        "meta": {},
        "metrics": {k: {"value": v[0], "is_latency": v[1]} for k, v in metrics.items()},
    }


def test_rate_regression_beyond_tolerance_fails():
    base = _baseline(意图分类准确率=(0.90, False), 工具调用_F1=(0.70, False))
    # 键名带连字符不能做 kwargs，直接拼 dict：
    base["metrics"]["工具调用-F1"] = {"value": 0.70, "is_latency": False}
    current = {"意图分类准确率": (0.80, False)}  # 0.80 < 0.90 - 0.05 → 回归
    gate = compare_to_baseline(current, base, tolerance=0.05)
    assert gate.passed is False
    v = next(x for x in gate.verdicts if x.name == "意图分类准确率")
    assert v.status == "regressed"
    assert v.baseline == 0.90 and v.current == 0.80
    assert abs(v.delta - (-0.10)) < 1e-9


def test_within_tolerance_is_ok():
    base = _baseline(意图分类准确率=(0.90, False))
    current = {"意图分类准确率": (0.86, False)}  # 降 0.04 ≤ 容差 0.05 → 不算回归
    gate = compare_to_baseline(current, base, tolerance=0.05)
    assert gate.passed is True
    v = next(x for x in gate.verdicts if x.name == "意图分类准确率")
    assert v.status == "ok"
    assert gate.guarded_count == 1


def test_non_gated_metric_change_does_not_block():
    # 延迟与回复质量即便变差，也不在 GATED_METRICS → 不进 verdict、不影响 passed。
    assert "端到端延迟" not in GATED_METRICS
    assert "回复质量通过率" not in GATED_METRICS
    base = _baseline(意图分类准确率=(0.90, False), 端到端延迟=(1.0, True))
    current = {"意图分类准确率": (0.90, False), "端到端延迟": (5.0, True)}  # 延迟暴涨
    gate = compare_to_baseline(current, base, tolerance=0.05)
    assert gate.passed is True
    assert all(v.name != "端到端延迟" for v in gate.verdicts)


def test_baseline_has_current_na_is_skipped():
    # 槽位在基线有值、本次 N/A（不入 current 视图）→ skipped，不影响 passed。
    base = _baseline(意图分类准确率=(0.90, False), 槽位抽取完整率=(0.8, False))
    current = {"意图分类准确率": (0.90, False)}  # 槽位缺席
    gate = compare_to_baseline(current, base, tolerance=0.05)
    assert gate.passed is True
    slot = next(x for x in gate.verdicts if x.name == "槽位抽取完整率")
    assert slot.status == "skipped"
    assert slot.baseline == 0.8
    # 槽位恒 N/A 场景：实守数为 2（意图 + 工具F1 二者中实际比对到的）。
    assert gate.guarded_count == 1  # 本例 current 只有意图，故实守 1


def test_current_has_baseline_missing_is_new():
    base = _baseline(意图分类准确率=(0.90, False))
    current = {"意图分类准确率": (0.90, False), "工具调用-F1": (0.6, False)}
    gate = compare_to_baseline(current, base, tolerance=0.05)
    assert gate.passed is True
    f1 = next(x for x in gate.verdicts if x.name == "工具调用-F1")
    assert f1.status == "new"
    assert f1.current == 0.6


def test_realistic_two_metric_guard():
    # 槽位恒 N/A 的现实场景：基线 3 项，当前只有意图 + 工具F1 → 实守 2 项。
    base = _baseline(意图分类准确率=(0.90, False), 槽位抽取完整率=(0.0, False))
    base["metrics"]["工具调用-F1"] = {"value": 0.70, "is_latency": False}
    current = {"意图分类准确率": (0.90, False), "工具调用-F1": (0.70, False)}
    gate = compare_to_baseline(current, base, tolerance=0.05)
    assert gate.guarded_count == 2
    assert gate.passed is True


# ── 渲染 ────────────────────────────────────────────────────────────────────

def test_format_gate_report_shows_values_and_count():
    base = _baseline(意图分类准确率=(0.90, False))
    current = {"意图分类准确率": (0.80, False)}
    gate = compare_to_baseline(current, base, tolerance=0.05)
    text = format_gate_report(gate)
    assert "回归" in text
    assert "FAIL" in text
    assert "实守 1 项" in text
    assert "退出码 3" in text


def test_format_gate_report_pass_is_quiet_but_conclusive():
    base = _baseline(意图分类准确率=(0.90, False))
    current = {"意图分类准确率": (0.90, False)}
    gate = compare_to_baseline(current, base, tolerance=0.05)
    text = format_gate_report(gate)
    assert "PASS" in text
    assert "退出码 3" not in text  # 通过时不提退出码 3
