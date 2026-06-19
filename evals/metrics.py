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

    # expected_* = 用例里写死的「标准答案」；actual_* = 本次跑分类器/loop 得到的「实际值」。
    # 各指标就是把这两边对比算占比。留 None 的维度表示「本次没测它」→ 报告会标 N/A 而非算 0。
    input: str
    expected_intent: str
    actual_intent: Optional[str] = None       # 实际分类结果；None=未分类
    expected_tools: Optional[list[str]] = None
    actual_tools: Optional[list[str]] = None   # None=本次没端到端跑 loop，拿不到实际工具
    expected_slots: Optional[dict[str, Any]] = None
    actual_slots: Optional[dict[str, Any]] = None
    latency_s: Optional[float] = None          # 这条用例耗时（秒）；None=没计时
    error: Optional[str] = None


@dataclass
class Metric:
    """单个指标的结果。``na=True`` 表示无可评估样本（显式 N/A，附原因）。"""

    name: str
    value: Optional[float] = None  # 比率 0..1 或延迟秒数；N/A 时为 None
    # numerator/denominator：让报告能显示「3/5」这种可核对的原始计数，而不只给个百分比。
    numerator: Optional[int] = None
    denominator: Optional[int] = None
    na: bool = False               # True=没有可评估样本，显式标 N/A（见 note 里的原因）
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)  # 指标专属附加数据（如延迟的 p50/max）


def intent_accuracy(results: list[EvalResult]) -> Metric:
    """意图分类准确率：actual_intent == expected_intent 的占比。"""
    # 「分母只含可评估样本」的范式（四个指标都遵循它）：先筛出真正测过这维度的用例，
    # 没有就标 N/A——绝不把「没测的」也算进分母伪造出一个虚低/虚高的准确率。
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
    # 必须 expected 和 actual「都有」才可评估：少任一边都没法对比，故剔出分母。
    eligible = [
        r for r in results if r.expected_tools is not None and r.actual_tools is not None
    ]
    if not eligible:
        # 典型场景：本次只跑了分类器、没真正驱动 AgentLoop，自然没有 actual_tools → N/A。
        return Metric(
            "工具调用正确率",
            na=True,
            note="本次运行未捕获实际工具调用（需端到端执行 AgentLoop）",
        )
    # 用 set 比较：「调了哪些工具」算对，与调用「顺序」无关（顺序不在本指标考核范围内）。
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
    # 「先单条算比例、再跨用例求平均」（宏平均）：每条用例权重相等，不被槽位多的用例带偏。
    per_case: list[float] = []
    for r in eligible:
        expected = r.expected_slots or {}
        actual = r.actual_slots or {}
        # 逐个期望槽位看「键存在且值相等」算命中；actual.get(k) 缺键返回 None，自然算未命中。
        hit = sum(1 for k, v in expected.items() if actual.get(k) == v)
        # 本条得分 = 命中数 / 期望槽位数；expected 为空时记 0 避免除零。
        per_case.append(hit / len(expected) if expected else 0.0)
    return Metric(
        "槽位抽取完整率",
        value=sum(per_case) / len(per_case),  # 各用例得分的算术平均
        denominator=len(eligible),
    )


def latency_summary(results: list[EvalResult]) -> Metric:
    """端到端延迟：对有计时的用例汇总 avg / p50 / max（秒）。"""
    # 先排序：p50（中位数）和 max 都靠「有序样本」取——sorted 后 [-1] 即最大值。
    samples = sorted(r.latency_s for r in results if r.latency_s is not None)
    if not samples:
        return Metric("端到端延迟", na=True, note="无计时样本")
    avg = sum(samples) / len(samples)
    # 近似中位数：取中间位的元素（偶数个时偏右一个，对评估够用，不必精确插值）。
    p50 = samples[len(samples) // 2]
    return Metric(
        "端到端延迟",
        value=avg,  # value 放 avg 作主数值；细分 p50/max 放 extra 供报告展开
        denominator=len(samples),
        extra={"avg_s": avg, "p50_s": p50, "max_s": samples[-1]},
    )


def build_report(results: list[EvalResult]) -> dict[str, Any]:
    """汇总全部指标 + 判错/异常用例清单。"""
    # 一次性算齐四个指标；每个指标各自决定要不要标 N/A（见上面各函数）。
    metrics = [
        intent_accuracy(results),
        tool_call_correctness(results),
        slot_completeness(results),
        latency_summary(results),
    ]
    # 单独拎出「分类判错」的用例，便于报告详列哪条错、错成了啥（成功的不展开 → 成功静默）。
    errors = [
        r
        for r in results
        if r.actual_intent is not None and r.actual_intent != r.expected_intent
    ]
    return {"metrics": metrics, "errors": errors, "total": len(results)}


def _fmt_metric(m: Metric) -> str:
    # 单个指标渲染成一行文本（{m.name:12} 是左对齐补空格到 12 宽，让各行列对齐）。
    if m.na:
        # N/A 显式打出来并附原因，不悄悄省略——读者一眼知道「不是 0 分，是没测」。
        return f"  {m.name:12} N/A（{m.note}）"
    if m.name == "端到端延迟":
        # 延迟是特例：不是百分比，而是从 extra 里取秒数三件套展示。
        e = m.extra
        return (
            f"  {m.name:12} avg {e['avg_s']:.3f}s / p50 {e['p50_s']:.3f}s / "
            f"max {e['max_s']:.3f}s（n={m.denominator}）"
        )
    # 其余三个都是比率：value(0..1) → 百分比。
    pct = (m.value or 0.0) * 100
    # 优先显示「分子/分母」这种可核对计数；只有分母时退而显示 n=；都没有就留空。
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
