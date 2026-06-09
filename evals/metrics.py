"""评估多指标计算（Phase 6 评估闭环）。

纯函数 + 数据类，**不触网、不依赖真实 provider**，故可离线确定性单测。
``evals/run_evals.py`` 负责跑真实分类器把每条用例填成 :class:`EvalResult`，再交由
本模块汇总为多指标报告。

指标（design.md D4：缺数据的指标显式标 N/A，不伪造分母、不静默跳过）：
- 意图分类准确率
- 工具调用正确率（仅当用例含 ``expected_tools`` 且本次实际捕获到 ``actual_tools``）
- 槽位抽取完整率（仅当用例含 ``expected_slots`` 且捕获到 ``actual_slots``）
- 端到端延迟（对有计时的用例汇总 avg / p50 / max）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = ["EvalResult", "Metric", "build_report", "format_report"]


@dataclass
class EvalResult:
    """单条用例的评估结果。未评估的维度留 ``None``，由报告据此标 N/A。"""

    input: str
    expected_intent: str
    actual_intent: Optional[str] = None
    expected_tools: Optional[list[str]] = None
    actual_tools: Optional[list[str]] = None
    expected_slots: Optional[dict[str, Any]] = None
    actual_slots: Optional[dict[str, Any]] = None
    latency_s: Optional[float] = None
    error: Optional[str] = None


@dataclass
class Metric:
    """单个指标的结果。``na=True`` 表示无可评估样本（显式 N/A，附原因）。"""

    name: str
    value: Optional[float] = None  # 比率 0..1 或延迟秒数；N/A 时为 None
    numerator: Optional[int] = None
    denominator: Optional[int] = None
    na: bool = False
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def intent_accuracy(results: list[EvalResult]) -> Metric:
    """意图分类准确率：actual_intent == expected_intent 的占比。"""
    eligible = [r for r in results if r.actual_intent is not None]
    if not eligible:
        return Metric("意图分类准确率", na=True, note="无已分类用例")
    correct = sum(1 for r in eligible if r.actual_intent == r.expected_intent)
    total = len(eligible)
    return Metric("意图分类准确率", value=correct / total, numerator=correct, denominator=total)


def tool_call_correctness(results: list[EvalResult]) -> Metric:
    """工具调用正确率：实际触发工具集合 == 期望工具集合（顺序无关）的占比。

    仅统计**同时**含 ``expected_tools`` 与 ``actual_tools`` 的用例；否则该用例不计入
    （分母只含可评估样本）。一条可评估样本都没有时返回 N/A。
    """
    eligible = [
        r for r in results if r.expected_tools is not None and r.actual_tools is not None
    ]
    if not eligible:
        return Metric(
            "工具调用正确率",
            na=True,
            note="本次运行未捕获实际工具调用（需端到端执行 AgentLoop）",
        )
    correct = sum(1 for r in eligible if set(r.actual_tools or []) == set(r.expected_tools or []))
    total = len(eligible)
    return Metric("工具调用正确率", value=correct / total, numerator=correct, denominator=total)


def slot_completeness(results: list[EvalResult]) -> Metric:
    """槽位抽取完整率：对每条用例，期望槽位中被正确填出的比例，再跨用例求平均。

    仅统计同时含 ``expected_slots`` 与 ``actual_slots`` 的用例；否则 N/A。
    """
    eligible = [
        r for r in results if r.expected_slots and r.actual_slots is not None
    ]
    if not eligible:
        return Metric(
            "槽位抽取完整率",
            na=True,
            note="用例未提供 expected_slots（或本次未捕获 actual_slots）",
        )
    per_case: list[float] = []
    for r in eligible:
        expected = r.expected_slots or {}
        actual = r.actual_slots or {}
        hit = sum(1 for k, v in expected.items() if actual.get(k) == v)
        per_case.append(hit / len(expected) if expected else 0.0)
    return Metric(
        "槽位抽取完整率",
        value=sum(per_case) / len(per_case),
        denominator=len(eligible),
    )


def latency_summary(results: list[EvalResult]) -> Metric:
    """端到端延迟：对有计时的用例汇总 avg / p50 / max（秒）。"""
    samples = sorted(r.latency_s for r in results if r.latency_s is not None)
    if not samples:
        return Metric("端到端延迟", na=True, note="无计时样本")
    avg = sum(samples) / len(samples)
    p50 = samples[len(samples) // 2]
    return Metric(
        "端到端延迟",
        value=avg,
        denominator=len(samples),
        extra={"avg_s": avg, "p50_s": p50, "max_s": samples[-1]},
    )


def build_report(results: list[EvalResult]) -> dict[str, Any]:
    """汇总全部指标 + 判错/异常用例清单。"""
    metrics = [
        intent_accuracy(results),
        tool_call_correctness(results),
        slot_completeness(results),
        latency_summary(results),
    ]
    errors = [
        r
        for r in results
        if r.actual_intent is not None and r.actual_intent != r.expected_intent
    ]
    return {"metrics": metrics, "errors": errors, "total": len(results)}


def _fmt_metric(m: Metric) -> str:
    if m.na:
        return f"  {m.name:12} N/A（{m.note}）"
    if m.name == "端到端延迟":
        e = m.extra
        return (
            f"  {m.name:12} avg {e['avg_s']:.3f}s / p50 {e['p50_s']:.3f}s / "
            f"max {e['max_s']:.3f}s（n={m.denominator}）"
        )
    pct = (m.value or 0.0) * 100
    frac = (
        f" {m.numerator}/{m.denominator}"
        if m.numerator is not None and m.denominator is not None
        else f"（n={m.denominator}）" if m.denominator is not None else ""
    )
    return f"  {m.name:12} {pct:.1f}%{frac}"


def format_report(report: dict[str, Any]) -> str:
    """渲染为文本：多指标总览 + 仅详列判错用例（成功静默）。"""
    lines = [f"\n评估多指标报告（共 {report['total']} 条用例）:"]
    for m in report["metrics"]:
        lines.append(_fmt_metric(m))
    errors = report["errors"]
    if errors:
        lines.append(f"\n意图判错 {len(errors)} 条:")
        for r in errors:
            lines.append(f"  - 输入: {r.input}")
            lines.append(f"    期望: {r.expected_intent}  实际: {r.actual_intent}")
    else:
        lines.append("\n意图全部判对。")
    return "\n".join(lines)
