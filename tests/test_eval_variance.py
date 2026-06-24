"""多次采样置信区间（改造 3）的离线确定性单测。

覆盖 t 分布 CI 半宽、跨 run 聚合、报告渲染与各边界（N=1、零方差、全 N/A）。
纯函数、不触网、不跑 LLM。
"""

import math

from evals.metrics import (
    Metric,
    AggregatedMetric,
    aggregate_runs,
    format_multisample_report,
    student_t_halfwidth,
)


def _report(metrics):
    return {"metrics": metrics, "errors": [], "total": 1}


# --------------------------------------------------------------------------- #
# student_t_halfwidth
# --------------------------------------------------------------------------- #
def test_halfwidth_two_values_uses_t_dist():
    # values [0.5, 0.7]: mean=0.6, 样本 s=sqrt(0.02)=0.1414, s/√2=0.1, t(df=1)=12.706
    # → 半宽 = 12.706 * 0.1 = 1.2706
    hw = student_t_halfwidth([0.5, 0.7])
    assert math.isclose(hw, 1.2706, rel_tol=1e-3)


def test_halfwidth_single_value_is_zero():
    # n<2：无 run-to-run 不确定性可估 → 半宽 0
    assert student_t_halfwidth([0.62]) == 0.0


def test_halfwidth_zero_variance_is_zero():
    # N 次完全相同（temp=0 抖动可忽略）→ s=0 → 半宽 0（稳定，不是异常）
    assert student_t_halfwidth([0.8, 0.8, 0.8]) == 0.0


def test_halfwidth_empty_is_zero():
    assert student_t_halfwidth([]) == 0.0


# --------------------------------------------------------------------------- #
# aggregate_runs
# --------------------------------------------------------------------------- #
def test_aggregate_runs_mean_and_n():
    reports = [
        _report([Metric("意图分类准确率", value=0.6, denominator=10)]),
        _report([Metric("意图分类准确率", value=0.8, denominator=10)]),
        _report([Metric("意图分类准确率", value=0.7, denominator=10)]),
    ]
    agg = aggregate_runs(reports)
    assert len(agg) == 1
    a = agg[0]
    assert a.name == "意图分类准确率"
    assert math.isclose(a.mean, 0.7, rel_tol=1e-9)
    assert a.n == 3
    assert not a.na
    assert a.half_width > 0  # 三个不同值 → 非零方差


def test_aggregate_runs_skips_na_observations():
    # 某指标某次 N/A：只纳入非 N/A 的观测，n 据此减少。
    reports = [
        _report([Metric("工具调用-参数级F1", value=0.5, denominator=4)]),
        _report([Metric("工具调用-参数级F1", na=True, note="无标注")]),
        _report([Metric("工具调用-参数级F1", value=0.5, denominator=4)]),
    ]
    agg = aggregate_runs(reports)
    a = agg[0]
    assert a.n == 2  # 跳过了 N/A 那次
    assert math.isclose(a.mean, 0.5, rel_tol=1e-9)
    assert a.half_width == 0.0  # 两个相同值 → 零方差


def test_aggregate_runs_all_na_marks_na():
    reports = [
        _report([Metric("工具调用-参数级F1", na=True, note="x")]),
        _report([Metric("工具调用-参数级F1", na=True, note="x")]),
    ]
    agg = aggregate_runs(reports)
    assert agg[0].na is True
    assert agg[0].mean is None


def test_aggregate_runs_preserves_metric_order():
    metrics = [Metric("意图分类准确率", value=0.7), Metric("工具调用-召回率", value=0.3)]
    reports = [_report(metrics), _report(metrics)]
    agg = aggregate_runs(reports)
    assert [a.name for a in agg] == ["意图分类准确率", "工具调用-召回率"]


def test_aggregate_runs_latency_flagged():
    reports = [
        _report([Metric("端到端延迟", value=5.0, extra={"avg_s": 5.0})]),
        _report([Metric("端到端延迟", value=7.0, extra={"avg_s": 7.0})]),
    ]
    agg = aggregate_runs(reports)
    assert agg[0].is_latency is True
    assert math.isclose(agg[0].mean, 6.0, rel_tol=1e-9)


# --------------------------------------------------------------------------- #
# format_multisample_report
# --------------------------------------------------------------------------- #
def test_format_multisample_shows_mean_ci_and_annotation():
    agg = [AggregatedMetric(name="意图分类准确率", mean=0.7, half_width=0.05, n=5)]
    out = format_multisample_report(agg, n_runs=5, total_cases=20)
    assert "20 条用例 × 5 次跑" in out
    assert "70.0% ± 5.0%（n=5 次）" in out
    # CI 含义标注：run-to-run 抖动、不含数据集误差
    assert "LLM 抖动" in out and "数据集大小" in out


def test_format_multisample_zero_variance_marks_stable():
    agg = [AggregatedMetric(name="意图分类准确率", mean=0.8, half_width=0.0, n=5)]
    out = format_multisample_report(agg, n_runs=5, total_cases=20)
    assert "80.0% ± 0.0%" in out
    assert "稳定" in out


def test_format_multisample_latency_in_seconds():
    agg = [AggregatedMetric(name="端到端延迟", mean=6.0, half_width=1.0, n=5, is_latency=True)]
    out = format_multisample_report(agg, n_runs=5, total_cases=20)
    assert "6.000s ± 1.000s（n=5 次）" in out


def test_format_multisample_na_metric():
    agg = [AggregatedMetric(name="工具调用-参数级F1", na=True)]
    out = format_multisample_report(agg, n_runs=5, total_cases=20)
    assert "N/A" in out
