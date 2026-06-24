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

import math
from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = [
    "EvalResult",
    "Metric",
    "build_report",
    "format_report",
    "aggregate_runs",
    "format_multisample_report",
    "student_t_halfwidth",
]


@dataclass
class EvalResult:
    """单条用例的评估结果。未评估的维度留 ``None``，由报告据此标 N/A。"""

    # expected_* = 用例里写死的「标准答案」；actual_* = 本次跑分类器/loop 得到的「实际值」。
    # 各指标就是把这两边对比算占比。留 None 的维度表示「本次没测它」→ 报告会标 N/A 而非算 0。
    input: str
    expected_intent: str
    actual_intent: Optional[str] = None       # 实际分类结果；None=未分类
    expected_tools: Optional[list[str]] = None  # 期望工具名（顺序无关）；标准答案侧仍只记名字
    # actual_tools「采全」：有序的 {"name", "args"} 列表（name 与 args 一并保留、保序）。
    # None=本次没端到端跑 loop，拿不到实际工具。
    # 设计：采全——数据采下 name+args+顺序；下方工具调用分档据此算召回/精确/F1（name 级）、
    # 参数级 F1（逐键比稳定键）、序列正确率（子序列匹配），各档独立 N/A。
    actual_tools: Optional[list[dict[str, Any]]] = None
    # 参数级比对的标注（改造 2，旁挂格式）：{工具名: {键: 值}}，只标稳定键。
    # 缺省 None → 参数级档对该用例记 N/A（不伪造）。比对时只比标注的键，actual 多出忽略。
    expected_tool_args: Optional[dict[str, dict[str, Any]]] = None
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


def _tool_eligible(results: list[EvalResult]) -> list[EvalResult]:
    """工具调用各档的公共可评估筛选：expected_tools 与 actual_tools 都有才可比。"""
    # 少任一边都没法对比，故剔出分母（典型：只跑了分类器、没驱动 loop → actual 为 None）。
    return [
        r for r in results if r.expected_tools is not None and r.actual_tools is not None
    ]


def _actual_names(r: EvalResult) -> list[str]:
    """从采全的 actual_tools（[{name, args}]）取出有序工具名列表。"""
    return [t["name"] for t in (r.actual_tools or [])]


def _normalize_arg(v: Any) -> str:
    """参数值的轻量归一化：统一成可比较的规范串（只覆盖稳定键涉及的类型）。

    - 数字与其字符串形态视为相等：``60`` ≡ ``"60"``（duration 常见歧义）。
    - 字符串去空白、转小写（gender ``Male``≡``male``）；中文不受 lower 影响。
    语义/相对时间等价不在此处（那需 LLM-judge，见改造 4），故只做确定性规范化。
    """
    if isinstance(v, bool):
        return str(v)  # bool 是 int 子类，单列以免 True 被当作 1
    if isinstance(v, (int, float)):
        # 整数值的 float（60.0）规整为 "60"，与 int 60 / 字符串 "60" 对齐。
        return str(int(v)) if float(v).is_integer() else str(v)
    return str(v).strip().lower()


def _args_match(expected_args: dict[str, Any], actual_args: dict[str, Any]) -> bool:
    """参数级匹配谓词：只比 expected 标注的键，逐键归一化后相等（actual 多出的键忽略）。"""
    for key, exp_val in expected_args.items():
        if key not in actual_args:
            return False  # 标注的键 actual 没有 → 不匹配
        if _normalize_arg(actual_args[key]) != _normalize_arg(exp_val):
            return False
    return True


def tool_call_recall_precision_f1(results: list[EvalResult]) -> list[Metric]:
    """颗粒度·部分给分：per-tool 的召回率/精确率/F1（name 级，按用例宏平均）。

    对每条可评估用例算 命中=set(actual名)∩set(expected名)，得 recall/precision/F1，
    再跨用例宏平均（每条等权，不被工具多的用例带偏）。无可评估样本时三档均 N/A。
    """
    eligible = _tool_eligible(results)
    if not eligible:
        note = "本次运行未捕获实际工具调用（需端到端执行 AgentLoop）"
        return [
            Metric("工具调用-召回率", na=True, note=note),
            Metric("工具调用-精确率", na=True, note=note),
            Metric("工具调用-F1", na=True, note=note),
        ]
    recalls: list[float] = []
    precisions: list[float] = []
    f1s: list[float] = []
    for r in eligible:
        expected = set(r.expected_tools or [])
        actual = set(_actual_names(r))
        hit = len(expected & actual)
        # 空集边界：期望为空时召回记 1（无所需即满足）；实际为空时精确记 1（没乱调）。
        recall = hit / len(expected) if expected else 1.0
        precision = hit / len(actual) if actual else 1.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        recalls.append(recall)
        precisions.append(precision)
        f1s.append(f1)
    n = len(eligible)
    return [
        Metric("工具调用-召回率", value=sum(recalls) / n, denominator=n),
        Metric("工具调用-精确率", value=sum(precisions) / n, denominator=n),
        Metric("工具调用-F1", value=sum(f1s) / n, denominator=n),
    ]


def tool_call_exact_match(results: list[EvalResult]) -> Metric:
    """对照档·完全匹配率：实际工具名集合 == 期望集合（全有或全无、顺序无关）。"""
    eligible = _tool_eligible(results)
    if not eligible:
        return Metric(
            "工具调用-完全匹配率",
            na=True,
            note="本次运行未捕获实际工具调用（需端到端执行 AgentLoop）",
        )
    correct = sum(1 for r in eligible if set(_actual_names(r)) == set(r.expected_tools or []))
    total = len(eligible)
    return Metric("工具调用-完全匹配率", value=correct / total, numerator=correct, denominator=total)


def tool_call_param_f1(results: list[EvalResult]) -> Metric:
    """严格度·参数级 F1：在 name 命中基础上，再要求该工具参数逐键匹配（只比标注的键）。

    仅对含 ``expected_tool_args`` 的用例计入（否则该用例 N/A，不伪造分母）。对一条用例：
    一个期望工具算「命中」当且仅当 actual 调了同名工具且其参数与标注逐键匹配；据此算
    参数级 recall/precision，取 F1，再跨用例宏平均。
    """
    eligible = [r for r in _tool_eligible(results) if r.expected_tool_args]
    if not eligible:
        return Metric(
            "工具调用-参数级F1",
            na=True,
            note="无用例标注 expected_tool_args（参数级比对需稳定键标注）",
        )
    f1s: list[float] = []
    for r in eligible:
        expected = list(r.expected_tools or [])
        # name → 该名下任一实际调用的 args（取首个同名调用比对；本项目无同名两次）。
        actual_by_name: dict[str, dict] = {}
        for t in r.actual_tools or []:
            actual_by_name.setdefault(t["name"], t.get("args") or {})
        exp_args = r.expected_tool_args or {}
        # 命中：名字调了 + （若该工具有参数标注则）参数逐键匹配。
        hit = 0
        for name in expected:
            if name not in actual_by_name:
                continue
            if name in exp_args and not _args_match(exp_args[name], actual_by_name[name]):
                continue
            hit += 1
        actual_names = set(actual_by_name)
        recall = hit / len(expected) if expected else 1.0
        precision = hit / len(actual_names) if actual_names else 1.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        f1s.append(f1)
    return Metric("工具调用-参数级F1", value=sum(f1s) / len(f1s), denominator=len(f1s))


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    """needle 是否为 haystack 的子序列（保持相对顺序，允许 haystack 中间夹杂其它元素）。"""
    it = iter(haystack)
    return all(x in it for x in needle)  # 对每个 needle 元素在剩余 haystack 里顺序找下一处


def tool_call_sequence_correctness(results: list[EvalResult]) -> Metric:
    """严格度·序列级：expected_tools（有序）是否为 actual 名字序列的子序列（按用例宏平均）。

    子序列匹配容忍 actual 多调/重复工具，只罚真实顺序违例（逆序）。
    """
    eligible = _tool_eligible(results)
    if not eligible:
        return Metric(
            "工具调用-序列正确率",
            na=True,
            note="本次运行未捕获实际工具调用（需端到端执行 AgentLoop）",
        )
    correct = sum(1 for r in eligible if _is_subsequence(list(r.expected_tools or []), _actual_names(r)))
    total = len(eligible)
    return Metric("工具调用-序列正确率", value=correct / total, numerator=correct, denominator=total)


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
    # 一次性算齐各指标；每个指标各自决定要不要标 N/A（见上面各函数）。
    # 工具调用分档（改造 2）：召回/精确/F1（颗粒度）→ 参数级F1、序列正确率（严格度）
    # → 完全匹配率（全有或全无对照），与宽松召回并列，一眼看出差距。
    metrics = [
        intent_accuracy(results),
        *tool_call_recall_precision_f1(results),
        tool_call_param_f1(results),
        tool_call_sequence_correctness(results),
        tool_call_exact_match(results),
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


# ════════════════════════════════════════════════════════════════════════════
# 多次采样与置信区间（改造 3：治非确定性）
#
# 量的是 temp=0 下的 run-to-run 残余抖动：整套用例重跑 N 次，把每次的聚合指标值
# 当作「一个观测」，对 N 个观测算 mean ± t 分布置信区间。CI 反映的是 LLM 抖动，
# 不含数据集大小的不确定性（20 条太小那块需更大用例集，见改造 8）。
# 计算全为纯函数、不触网，故可离线确定性单测（与触网的采样循环解耦）。
# ════════════════════════════════════════════════════════════════════════════

# 95% 双侧 t 临界值表（t_{df, 0.975}），df=1..30。小样本必须用 t 而非正态 z=1.96。
# 硬编码而非引 scipy：为一张静态表加重依赖不划算（零依赖、可单测）。
_T_CRIT_95: dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080,
    22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048,
    29: 2.045, 30: 2.042,
}
# df>30 退化用正态近似（t 已很接近 z=1.96，误差可忽略）。
_Z_95 = 1.96


def _t_crit_95(df: int) -> float:
    """取自由度 df 的 95% 双侧 t 临界值；df>30 退化用 z=1.96。"""
    if df <= 0:
        return 0.0
    return _T_CRIT_95.get(df, _Z_95)


def student_t_halfwidth(values: list[float]) -> float:
    """一组观测值的 95% t 置信区间「半宽」：``t_(n-1,0.975) · s/√n``。

    - n<2：无法估方差，半宽=0（单次跑没有 run-to-run 不确定性可言）。
    - s=0（N 次完全相同，如 temp=0 抖动可忽略）：半宽=0，是「链路稳定」的结论而非异常。
    s 为样本标准差（n-1 分母）。
    """
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    # 样本方差（n-1 分母）：无偏估计，配合 t 分布。
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    s = math.sqrt(var)
    # 近零方差按零处理：相同值因浮点累加会留下 ~1e-16 的残渣，不应据此报出非零 CI。
    if s < 1e-9:
        return 0.0
    return _t_crit_95(n - 1) * s / math.sqrt(n)


@dataclass
class AggregatedMetric:
    """跨 N 次跑聚合后的单个指标：mean ± 半宽（run-to-run 抖动的 95% t-CI）。"""

    name: str
    mean: Optional[float] = None   # N 次非 N/A 观测的均值；全 N/A 时 None
    half_width: float = 0.0        # 95% t-CI 半宽；n<2 或零方差时为 0
    n: int = 0                     # 纳入的非 N/A 观测数
    na: bool = False               # True=N 次全 N/A
    is_latency: bool = False       # 延迟指标渲染为秒而非百分比


def aggregate_runs(reports: list[dict[str, Any]]) -> list[AggregatedMetric]:
    """把 N 次跑的报告（各含 ``metrics``）按指标名聚合为 mean ± t-CI 半宽。

    每个指标只纳入「该次跑非 N/A」的观测值；某指标 N 次全 N/A 则整体标 N/A。
    指标顺序沿用第一次跑的顺序（保持报告可读性一致）。
    """
    if not reports:
        return []
    # 以第一次跑的指标顺序为准，逐个指标跨 run 收集非 N/A 的 value。
    ordered_names = [m.name for m in reports[0]["metrics"]]
    out: list[AggregatedMetric] = []
    for name in ordered_names:
        values: list[float] = []
        is_latency = name == "端到端延迟"
        for rep in reports:
            for m in rep["metrics"]:
                if m.name == name and not m.na and m.value is not None:
                    values.append(m.value)
                    break
        if not values:
            out.append(AggregatedMetric(name=name, na=True, is_latency=is_latency))
            continue
        mean = sum(values) / len(values)
        out.append(
            AggregatedMetric(
                name=name,
                mean=mean,
                half_width=student_t_halfwidth(values),
                n=len(values),
                is_latency=is_latency,
            )
        )
    return out


def format_multisample_report(
    aggregated: list[AggregatedMetric], n_runs: int, total_cases: int
) -> str:
    """渲染多采样报告：每指标 ``mean ± 半宽（n=N 次）``，并标注 CI 含义。"""
    lines = [
        f"\n评估多采样报告（{total_cases} 条用例 × {n_runs} 次跑）:",
        "  （置信区间为 95% t 分布；反映 run-to-run 的 LLM 抖动，"
        "不含数据集大小的不确定性——后者需更大用例集）",
    ]
    for a in aggregated:
        if a.na:
            lines.append(f"  {a.name:14} N/A（{n_runs} 次均无可评估样本）")
            continue
        if a.is_latency:
            # 延迟：秒；半宽也以秒计。
            stable = "（稳定）" if a.half_width == 0.0 else ""
            lines.append(
                f"  {a.name:14} {a.mean:.3f}s ± {a.half_width:.3f}s（n={a.n} 次）{stable}"
            )
            continue
        # 比率：转百分比；零方差标注稳定。
        mean_pct = a.mean * 100
        hw_pct = a.half_width * 100
        stable = "（稳定，零方差）" if a.half_width == 0.0 else ""
        lines.append(
            f"  {a.name:14} {mean_pct:.1f}% ± {hw_pct:.1f}%（n={a.n} 次）{stable}"
        )
    return "\n".join(lines)
