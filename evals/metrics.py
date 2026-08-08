"""评估多指标计算（Phase 6 评估闭环）。

纯函数 + 数据类，**不触网、不依赖真实 provider**，故可离线确定性单测。
``evals/run_evals.py`` 负责端到端真跑把每条用例填成 :class:`EvalResult`，再交由
本模块汇总为多指标报告。

指标（design.md D4：缺数据的指标显式标 N/A，不伪造分母、不静默跳过）：
- 工具调用正确率（仅当用例含 ``expected_tools`` 且本次实际捕获到 ``actual_tools``）
- 槽位抽取完整率（仅当用例含 ``expected_slots`` 且捕获到 ``actual_slots``）
- 端到端延迟（对有计时的用例汇总 avg / p50 / max；口径=端到端真跑全程耗时）

（change retire-legacy-intent-classifier）意图分类准确率已退役：旧分类器退出主服务
链路后该指标度量的是不服务用户的组件；意图理解由工具选择体现，被工具级指标覆盖。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

__all__ = [
    "EvalResult",
    "Metric",
    "build_report",
    "format_report",
    "aggregate_runs",
    "format_multisample_report",
    "student_t_halfwidth",
    "response_quality",
    "judge_human_agreement",
    "slots_from_tool_calls",
    "task_success_rate",
    # 工具调用 F1 的正/负样本分档（change evals-f1-polarity-breakdown）
    "tool_call_f1_by_polarity",
    "F1_POSITIVE",
    "F1_NEGATIVE",
    "POLARITY_METRICS",
    # 回归门禁（改造 6）；被守指标集随域声明（change oncall-evals-bootstrap）
    "validate_gated_metrics",
    "BASELINE_SCHEMA_VERSION",
    "GateVerdict",
    "GateReport",
    "report_to_baseline",
    "aggregated_to_baseline",
    "compare_to_baseline",
    "format_gate_report",
]


@dataclass
class EvalResult:
    """单条用例的评估结果。未评估的维度留 ``None``，由报告据此标 N/A。"""

    # expected_* = 用例里写死的「标准答案」；actual_* = 本次端到端真跑得到的「实际值」。
    # 各指标就是把这两边对比算占比。留 None 的维度表示「本次没测它」→ 报告会标 N/A 而非算 0。
    input: str
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
    # 任务成功率（change evals-task-success-rate）：期望达成的业务终态工具名 + 实际工具执行成败。
    # expected_outcome=None → 该用例不计入任务成功率（无工具终态，如 pay/statistics/other）。
    # actual_tool_outcomes：[{name, ok}]（来自 collect_tool_outcomes）；None=未真跑 loop → N/A。
    expected_outcome: Optional[str] = None
    actual_tool_outcomes: Optional[list[dict[str, Any]]] = None
    latency_s: Optional[float] = None          # 这条用例耗时（秒）；None=没计时
    # LLM-as-judge 对最终回复的二元裁决（改造 4）：None=本次未开 --judge（回复质量记 N/A）。
    judge_passed: Optional[bool] = None
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


def _case_rpf(r: EvalResult) -> tuple[float, float, float]:
    """单条用例的工具名级 (recall, precision, F1)。

    总 F1 与分档 F1 **共用这一个函数**，不是各写一份——两边一旦分叉，
    「总 F1 = 两档按占比加权」这个关系就不成立，而那个关系正是分档要传达的东西
    （也是 `test_polarity_split_is_weight_consistent` 守的东西）。
    """
    expected = set(r.expected_tools or [])
    actual = set(_actual_names(r))
    hit = len(expected & actual)
    # 空集边界：期望为空时召回记 1（无所需即满足）；实际为空时精确记 1（没乱调）。
    # ★ 这一行就是「免费满分」的入口，也是分档要隔离的那批样本的判据。
    recall = hit / len(expected) if expected else 1.0
    precision = hit / len(actual) if actual else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return recall, precision, f1


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
        recall, precision, f1 = _case_rpf(r)   # 与分档共用，见 _case_rpf 的说明
        recalls.append(recall)
        precisions.append(precision)
        f1s.append(f1)
    n = len(eligible)
    return [
        Metric("工具调用-召回率", value=sum(recalls) / n, denominator=n),
        Metric("工具调用-精确率", value=sum(precisions) / n, denominator=n),
        Metric("工具调用-F1", value=sum(f1s) / n, denominator=n),
    ]


#: 分档指标名（模块级常量：报告渲染要认它们、门禁守护测试要断言它们不在 GATED_METRICS，
#: 三处散着写字符串迟早对不上）。
F1_POSITIVE = "工具调用-F1(正样本)"
F1_NEGATIVE = "工具调用-F1(负样本)"
POLARITY_METRICS: tuple[str, ...] = (F1_POSITIVE, F1_NEGATIVE)


def tool_call_f1_by_polarity(results: list[EvalResult]) -> list[Metric]:
    """`工具调用-F1` 按**正/负样本**分档（change `evals-f1-polarity-breakdown`）。

    为什么要分：宏平均对空期望集给免费满分（`if expected else 1.0`），故总 F1 是
    **按正/负构成比例加权的平均数**，不是能力指标。实测过一次——负样本占比 37%→58%
    时 F1 从 56.2% 机械升到 78.5%，同期难例占比反而从 65% 掉到 38%，模型能力毫无变化。

    切分依据是 **`expected_tools` 是否为空**，不是意图类别（design D1）：意图是域绑定的，
    换到 oncall 就没有 `pay`/`statistics`；而免费满分的入口恰恰就是"期望集为空"这件事。

    每档带 ``extra["share"]``（占可评估集的比例）。**占比不能省**：只给两个 F1 值，
    读者仍无法判断总数为何是这个数；给了占比，加权关系自明。
    """
    eligible = _tool_eligible(results)
    if not eligible:
        note = "本次运行未捕获实际工具调用（需端到端执行 AgentLoop）"
        return [Metric(F1_POSITIVE, na=True, note=note), Metric(F1_NEGATIVE, na=True, note=note)]

    total = len(eligible)
    positive = [r for r in eligible if r.expected_tools]
    negative = [r for r in eligible if not r.expected_tools]

    def _bucket(name: str, rows: list[EvalResult], label: str) -> Metric:
        if not rows:
            # 记 0 会被读成「这档全错」——与「没有样本」意思相反，故标 N/A（design D6）。
            return Metric(name, na=True, note=f"本次可评估集中无{label}样本")
        return Metric(
            name,
            value=sum(_case_rpf(r)[2] for r in rows) / len(rows),
            denominator=len(rows),
            extra={"share": len(rows) / total},
        )

    return [_bucket(F1_POSITIVE, positive, "正"), _bucket(F1_NEGATIVE, negative, "负")]


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


def response_quality(results: list[EvalResult], calibrated: bool = False) -> Metric:
    """回复质量通过率（LLM-as-judge，改造 4）：judge 判 passed 的占比。

    仅统计含 ``judge_passed`` 的用例（未开 ``--judge`` 时全 None → N/A，不伪造分母）。
    ``calibrated=False`` 时在 note 标「未校准」——judge 未与人工标注算过一致率前，其结果
    MUST NOT 被当作可信真值（与全项目 N/A 诚实一致）。
    """
    eligible = [r for r in results if r.judge_passed is not None]
    if not eligible:
        return Metric(
            "回复质量通过率",
            na=True,
            note="本次未开启 LLM-judge（--judge）或未捕获回复",
        )
    passed = sum(1 for r in eligible if r.judge_passed)
    note = "" if calibrated else "judge 未校准（κ 未测）——自我偏好等偏差未经人工验证"
    return Metric(
        "回复质量通过率",
        value=passed / len(eligible),
        numerator=passed,
        denominator=len(eligible),
        note=note,
    )


def judge_human_agreement(
    judge_labels: list[bool], human_labels: list[bool]
) -> dict[str, float]:
    """judge 与人工二元标注的一致率与 Cohen's κ（校准用，纯函数）。

    一致率 = 两者判定相同的占比；κ 在此基础上扣除「随机一致」的部分（κ=1 完全一致、
    κ≈0 仅随机水平）。要求两列等长且非空。
    """
    if len(judge_labels) != len(human_labels):
        raise ValueError("judge 与人工标注数量不一致，无法配对")
    n = len(judge_labels)
    if n == 0:
        raise ValueError("校准集为空")
    po = sum(1 for j, h in zip(judge_labels, human_labels) if j == h) / n  # 观测一致率
    # 期望（随机）一致率：两列各自「判 pass」的边缘概率，按独立假设组合。
    pj = sum(1 for j in judge_labels if j) / n
    ph = sum(1 for h in human_labels if h) / n
    pe = pj * ph + (1 - pj) * (1 - ph)
    if pe >= 1.0:  # 退化：一方全 pass 或全 fail 且与另一方边缘一致 → κ 无定义，按一致与否取 1/0
        kappa = 1.0 if po >= 1.0 else 0.0
    else:
        kappa = (po - pe) / (1 - pe)
    return {"n": float(n), "agreement": po, "kappa": kappa}


# 工具 schema 的可选槽位默认占位串（见 harness/tools/schemas.py 的 FindTechnicianArgs）——
# 表示「模型没填、工具兜底」，不算模型抽到的槽位，还原时跳过以免完整率被默认值虚高。
# 这条是**域无关**的：任何域的「默认值不是模型的抽取成果」都成立，故留在机制侧。
_SLOT_SENTINELS: frozenset[str] = frozenset({"未知", "无"})


def slots_from_tool_calls(
    tool_calls: Optional[list[dict[str, Any]]],
    slot_key_map: Mapping[str, str],
) -> Optional[dict[str, Any]]:
    """从有序工具调用序列还原扁平的实际槽位 dict（纯函数，不触网）。

    槽位分散在多个工具的 args 里（预约域即 find_technician / create_appointment /
    check_availability），本函数把它们合并进一份扁平 dict，作 ``slot_completeness``
    的 ``actual_slots`` 输入。

    Args:
        tool_calls: 有序工具调用 ``[{name, args}]``。
        slot_key_map: **工具入参名 → 槽位键**的归一映射，由当前领域包声明
            （``Domain.eval_profile.slot_key_map``，change oncall-evals-bootstrap）。
            本模块不再内置任何具体领域的槽位名——那会让「机制域无关」名不副实。
            **空映射**表示本域不度量槽位完整率，直接返回 ``None``（指标恒 N/A）。

    规则（change evals-wire-slot-completeness 的 spec）：
    - **跨工具合并**：各工具 args 中的槽位字段并入同一 dict；映射里声明的别名
      （如 ``technician_name``）归一为其槽位键（``technician``）。
    - **同名冲突 last-write-wins**：按 ``tool_calls`` 顺序，后出现的工具调用覆盖先出现的
      同名槽位（确定性，不依赖 dict 遍历顺序）。
    - **哨兵默认值不计入**：``未知`` / ``无`` 视为「未抽取」，跳过（既不写入，也不覆盖已有真值）。
    - **空/None**：``tool_calls`` 为空或 None（真跑失败/未跑 loop）时返回 ``None``，使该用例
      槽位指标标 N/A，不伪造空 dict 当作「抽取了 0 个槽位」。有工具调用但无槽位字段则返回 ``{}``
      （区别于 None：表示「跑了但没抽到」，计 0 分而非 N/A）。
    """
    if not slot_key_map:  # 本域不度量槽位（显式声明），与「跑失败」同样标 N/A
        return None
    if not tool_calls:
        return None
    slots: dict[str, Any] = {}
    for call in tool_calls:
        args = call.get("args") or {}
        for arg_key, slot_key in slot_key_map.items():
            if arg_key not in args:
                continue
            val = args[arg_key]
            if isinstance(val, str) and val in _SLOT_SENTINELS:
                continue  # 哨兵默认值不算已抽取（也不覆盖先前真值）
            slots[slot_key] = val  # 顺序遍历，后者覆盖前者 → last-write-wins
    return slots


def slot_completeness(results: list[EvalResult], *, measured: bool = True) -> Metric:
    """槽位抽取完整率（**存在性口径**）：期望槽位中「被抽出」的比例，跨用例宏平均。

    存在性口径（change evals-wire-slot-completeness D8）：命中 = 期望槽位的**键存在**于
    ``actual_slots``，**不比精确值**。哨兵默认值已在 ``slots_from_tool_calls`` 剔除，故「键存在」
    即等价于「抽到了非默认的真实值」。这与 ``expected_tool_args`` 喂的参数级 P/R/F1（比精确值）
    口径分明：本指标度量「抽没抽到」（coverage），后者度量「抽得对不对」（accuracy）。
    选此口径的实测依据：当前 agent 抽出的值为自由文本且不规范（如 gender='男'、start_time 可能
    算错日期），精确匹配会令指标几乎恒 miss、失去意义。

    仅统计同时含 ``expected_slots`` 与 ``actual_slots`` 的用例；否则 N/A。``expected_slots``
    的**值仅作人类可读说明、不参与判定**——只用其键集合。

    ``measured=False``（域声明了空 ``slot_key_map``）时直接标 N/A 并给出**不同的 note**：
    「本域不度量」是设计，「本次未捕获」是抖动，两者混为一谈会让人误以为指标坏了、
    或反过来误以为一切正常（change oncall-evals-bootstrap）。
    """
    if not measured:
        return Metric(
            "槽位抽取完整率",
            na=True,
            note="本域不度量该项（域声明的 slot_key_map 为空）",
        )
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
        # 存在性：期望槽位的键在 actual 中即算命中（值不参与判定）。
        hit = sum(1 for k in expected if k in actual)
        # 本条得分 = 命中数 / 期望槽位数；expected 为空时记 0 避免除零。
        per_case.append(hit / len(expected) if expected else 0.0)
    return Metric(
        "槽位抽取完整率",
        value=sum(per_case) / len(per_case),  # 各用例得分的算术平均
        denominator=len(eligible),
    )


def task_success_rate(results: list[EvalResult]) -> Metric:
    """任务成功率（系统级/业务级，change evals-task-success-rate）：agent 是否达成业务终态。

    区别于「意图/工具调对没」，本指标问「任务**办成了没**」。一条用例「成功」当且仅当其
    ``expected_outcome`` 指定的终态工具在 ``actual_tool_outcomes`` 中出现**且执行未失败**
    （``ok is True``；同名多次任一成功即算成功——贴合「办成了」语义）。

    仅统计标了 ``expected_outcome`` 且本次捕获到 ``actual_tool_outcomes`` 的用例（宏平均、
    每条等权）；否则该用例不计入。全部不计入 → N/A（不伪造分母）。无工具终态的意图
    （pay/statistics/other）不标 ``expected_outcome``，故恒不计入。

    ⚠️ **口径**：这是**离线任务完成度的业务信号代理**，非真实转化率/满意度/人工介入率
    （那些需真实用户流量，属生产级）。v1 不纳入门禁（见 GATED_METRICS）。
    """
    eligible = [
        r for r in results if r.expected_outcome and r.actual_tool_outcomes is not None
    ]
    if not eligible:
        return Metric(
            "任务成功率",
            na=True,
            note="无用例标注 expected_outcome（或本次未真跑捕获工具执行）",
        )
    success = 0
    for r in eligible:
        outcomes = r.actual_tool_outcomes or []
        # 成功：终态工具出现过且其中至少一次 ok=True。
        if any(o.get("name") == r.expected_outcome and o.get("ok") for o in outcomes):
            success += 1
    return Metric(
        "任务成功率",
        value=success / len(eligible),
        numerator=success,
        denominator=len(eligible),
        note="离线完成度代理，非真实业务 KPI",
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


def build_report(results: list[EvalResult], *, measures_slots: bool = True) -> dict[str, Any]:
    """汇总全部指标 + 判错/异常用例清单。

    ``measures_slots``：本次运行的域是否度量槽位完整率（取自 ``eval_profile``）。这是个
    **布尔开关而非域概念**——报告层不认识"哪个域"，只认识"这次量不量它"。
    """
    # 一次性算齐各指标；每个指标各自决定要不要标 N/A（见上面各函数）。
    # 工具调用分档（改造 2）：召回/精确/F1（颗粒度）→ 参数级F1、序列正确率（严格度）
    # → 完全匹配率（全有或全无对照），与宽松召回并列，一眼看出差距。
    metrics = [
        *tool_call_recall_precision_f1(results),
        # 紧跟总 F1：分档要和它挨着才看得出「总 F1 = 两档按占比加权」
        # （change evals-f1-polarity-breakdown 的 design D3）。
        *tool_call_f1_by_polarity(results),
        tool_call_param_f1(results),
        tool_call_sequence_correctness(results),
        tool_call_exact_match(results),
        response_quality(results),  # 回复质量（LLM-judge，改造 4）；未开 --judge 时 N/A
        slot_completeness(results, measured=measures_slots),
        task_success_rate(results),  # 任务成功率（系统级/业务级，change evals-task-success-rate）
        latency_summary(results),
    ]
    return {"metrics": metrics, "total": len(results)}


def _fmt_metric(m: Metric) -> str:
    # 单个指标渲染成一行文本（{m.name:12} 是左对齐补空格到 12 宽，让各行列对齐）。
    if m.name in POLARITY_METRICS:
        # 分档是特例：缩进 + 树线挂在总 F1 下，视觉上是**一组三行**而不是"多了两个指标"。
        # **N/A 也走这一支**——否则空档会跳出缩进、看起来像个不相干的指标。
        tee = "├" if m.name == F1_POSITIVE else "└"
        label = m.name.split("(")[1].rstrip(")")     # "正样本" / "负样本"
        if m.na:
            return f"    {tee} {label:9} N/A（{m.note}）"
        # 占比必须打出来——它是「总 F1 是两档按占比加权」这个结论的全部依据（design D3）。
        share = m.extra.get("share")
        share_txt = f"，占 {share * 100:.0f}%" if share is not None else ""
        return (
            f"    {tee} {label:9} {(m.value or 0.0) * 100:.1f}%"
            f"（n={m.denominator}{share_txt}）"
        )
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
    # 非 N/A 但带 note（如 judge「未校准」提示）的也要打出来，不静默吞掉。
    suffix = f"  ⚠ {m.note}" if m.note else ""
    return f"  {m.name:12} {pct:.1f}%{frac}{suffix}"


def format_report(report: dict[str, Any]) -> str:
    """渲染为文本：多指标总览（成功静默，异常/N-A 原因已随各指标行给出）。"""
    lines = [f"\n评估多指标报告（共 {report['total']} 条用例）:"]
    for m in report["metrics"]:
        lines.append(_fmt_metric(m))
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
    # 正/负样本分档的构成占比（N 次的均值；非分档指标为 None）。
    # 它是 run 级量而非跨 run 统计量，故取均值即可——同一数据集各次跑的构成本应相同，
    # 只在某次跑有用例异常导致落出 `_tool_eligible` 时才会微动。
    share: Optional[float] = None
    # 全 N/A 时沿用单次报告的原因说明。**必须带过来**：「本域不度量该项」（设计）与
    # 「本次未捕获」（抖动）是两回事，只报一句「N 次均无可评估样本」会把二者抹平。
    note: Optional[str] = None


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
        shares: list[float] = []
        is_latency = name == "端到端延迟"
        for rep in reports:
            for m in rep["metrics"]:
                if m.name == name and not m.na and m.value is not None:
                    values.append(m.value)
                    if "share" in m.extra:
                        shares.append(m.extra["share"])
                    break
        if not values:
            # 取第一次跑该指标的 note 作为原因（N 次全 N/A，原因必然同一个）。
            note = next(
                (m.note for rep in reports for m in rep["metrics"] if m.name == name and m.note),
                None,
            )
            out.append(AggregatedMetric(name=name, na=True, is_latency=is_latency, note=note))
            continue
        mean = sum(values) / len(values)
        out.append(
            AggregatedMetric(
                name=name,
                mean=mean,
                half_width=student_t_halfwidth(values),
                n=len(values),
                is_latency=is_latency,
                # 分档占比要一路带到多采样视图——`--samples 3` 才是推荐跑法，
                # 占比在那里丢了等于本变更的主张在主视图上不成立（design D3）。
                share=(sum(shares) / len(shares)) if shares else None,
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
        if a.name in POLARITY_METRICS:
            # 与单采样视图同构：缩进 + 树线挂在总 F1 下，并保留占比。
            tee = "├" if a.name == F1_POSITIVE else "└"
            label = a.name.split("(")[1].rstrip(")")
            if a.na:
                lines.append(f"    {tee} {label:11} N/A（{a.note or f'{n_runs} 次均无可评估样本'}）")
                continue
            share_txt = f"，占 {a.share * 100:.0f}%" if a.share is not None else ""
            stable = "（稳定，零方差）" if a.half_width == 0.0 else ""
            lines.append(
                f"    {tee} {label:11} {a.mean * 100:.1f}% ± {a.half_width * 100:.1f}%"
                f"（n={a.n} 次{share_txt}）{stable}"
            )
            continue
        if a.na:
            lines.append(f"  {a.name:14} N/A（{a.note or f'{n_runs} 次均无可评估样本'}）")
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


# ════════════════════════════════════════════════════════════════════════════
# 基线持久化与回归门禁（改造 6）
#
# 设计取舍（见 change evals-ci-regression-gate 的 design.md）：
# - 基线存「全部非 N/A 指标」的快照（供历史/参照），但门禁只守 GATED_METRICS 子集。
# - 排除 latency（环境噪声、非正确性信号）与 response_quality（judge 未校准、不可当真值）；
#   工具调用 6 个子指标里只守 F1（name 级部分给分、平滑退化）。
# - 比对/序列化全为纯函数（不触网、不读写文件），IO 与退出码留在 run_evals.py。
# - 容差吸收 LLM 的 run-to-run 抖动：比率回归 ⟺ 当前 < 基线 − 容差。
# ════════════════════════════════════════════════════════════════════════════

# 门禁守哪些指标**由领域包声明**（``Domain.eval_profile.gated_metrics``，change
# oncall-evals-bootstrap）——此前这里是个全局常量 GATED_METRICS，装上另一个域的数据时
# 第二项会恒 N/A，门禁**静默**退化成只守 1 项而报告里看不出异常。那是最坏的一种失败。
#
# 但「哪些指标**不准**被守」是域无关的判断，留在机制侧：
_UNGATABLE_METRICS: frozenset[str] = frozenset({
    "端到端延迟",        # 机器/网络/API 负载相关，跨环境抖动大，非正确性信号
    "回复质量通过率",     # 来自未校准 judge，按项目诚实原则不可当真值
    # 工具调用的其余分档：与 F1 同一底层行为，守它们等于同一信号算多遍
    "工具调用-召回率",
    "工具调用-精确率",
    "工具调用-序列正确率",
    "工具调用-完全匹配率",
    F1_POSITIVE,
    F1_NEGATIVE,
})


def validate_gated_metrics(gated: tuple[str, ...], known_names: set[str]) -> None:
    """校验某域声明的被守指标集（语义校验，见 design D2 的分层理由）。

    这层校验在 ``evals/`` 而非 ``domains/``：指标名全集与「哪些不准守」的判断都在本模块，
    而依赖方向是 ``evals → domains``，反过来 import 会成环。

    Args:
        gated: 域声明的被守指标名。
        known_names: 本次报告实际产出的全部指标名（拼错即在此暴露）。

    Raises:
        ValueError: 名字不存在、或声明了不准被守的指标。**不静默跳过**——静默跳过
            一个拼错的名字，等于门禁少守一项而没人知道。
    """
    unknown = [n for n in gated if n not in known_names]
    if unknown:
        raise ValueError(
            f"门禁声明了不存在的指标名 {unknown}；可用指标：{sorted(known_names)}"
        )
    banned = [n for n in gated if n in _UNGATABLE_METRICS]
    if banned:
        raise ValueError(
            f"门禁不得守这些指标 {banned}——延迟是环境噪声、回复质量来自未校准 judge、"
            f"工具调用的其余分档与 F1 是同一底层行为（同一信号算多遍）"
        )

# 基线 JSON 结构版本；将来结构变化时门禁可据此拒绝/迁移旧基线。
BASELINE_SCHEMA_VERSION = 1

# 延迟型指标名（比对方向相反：越大越差）。当前不在 GATED_METRICS 内，保留供将来。
_LATENCY_METRIC = "端到端延迟"


@dataclass
class GateVerdict:
    """单个被守指标的门禁裁决。

    status:
    - ``ok``        当前未较基线回归（在容差内）。
    - ``regressed`` 当前较基线回归超过容差。
    - ``skipped``   基线有该指标但本次为 N/A（无法比对，不判对错）。
    - ``new``       本次有该指标但基线没有（信息提示，不判对错）。
    """

    name: str
    status: str
    baseline: Optional[float] = None
    current: Optional[float] = None
    delta: Optional[float] = None  # current - baseline（正=升，负=降）；仅 ok/regressed 有
    is_latency: bool = False


@dataclass
class GateReport:
    """门禁整体结果：逐指标裁决 + 是否通过 + 实守指标数。"""

    verdicts: list[GateVerdict] = field(default_factory=list)
    passed: bool = True            # 无任一 regressed 即通过
    guarded_count: int = 0         # 真正比对到的（ok/regressed）项数——「门禁实守 N 项」
    tolerance: float = 0.0


def _metric_value_view(m: Metric) -> Optional[tuple[float, bool]]:
    """把一个 ``Metric`` 提成 ``(value, is_latency)``；N/A 或无值返回 None（不入比对视图）。"""
    if m.na or m.value is None:
        return None
    return (m.value, m.name == _LATENCY_METRIC)


def _aggregated_value_view(a: "AggregatedMetric") -> Optional[tuple[float, bool]]:
    """把一个 ``AggregatedMetric`` 提成 ``(mean, is_latency)``；N/A 返回 None。"""
    if a.na or a.mean is None:
        return None
    return (a.mean, a.is_latency)


def report_to_baseline(
    report: dict[str, Any], *, total_cases: int, samples: int
) -> dict[str, Any]:
    """单次报告 → 基线 dict（D1 结构）。收全部非 N/A 指标，记 value + is_latency。"""
    metrics: dict[str, dict[str, Any]] = {}
    for m in report["metrics"]:
        view = _metric_value_view(m)
        if view is None:  # N/A 不写入基线（不伪造可比项）
            continue
        value, is_latency = view
        metrics[m.name] = {"value": value, "is_latency": is_latency}
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "meta": {"total_cases": total_cases, "samples": samples},
        "metrics": metrics,
    }


def aggregated_to_baseline(
    aggregated: list["AggregatedMetric"], *, total_cases: int, samples: int
) -> dict[str, Any]:
    """多采样聚合（用 mean）→ 基线 dict。跳过 N/A 指标。"""
    metrics: dict[str, dict[str, Any]] = {}
    for a in aggregated:
        view = _aggregated_value_view(a)
        if view is None:
            continue
        value, is_latency = view
        metrics[a.name] = {"value": value, "is_latency": is_latency}
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "meta": {"total_cases": total_cases, "samples": samples},
        "metrics": metrics,
    }


def compare_to_baseline(
    current: dict[str, tuple[float, bool]],
    baseline: dict[str, Any],
    tolerance: float,
    *,
    gated: tuple[str, ...],
) -> GateReport:
    """门禁裁决（纯函数）：只比对 ``gated`` 子集，对回归出整体 pass/fail。

    Args:
        current: ``{指标名: (value, is_latency)}``——本次跑的可比指标（N/A 项不应入此 dict）。
        baseline: 基线 dict（``report_to_baseline``/``aggregated_to_baseline`` 的产物）。
        tolerance: 容差；比率回归 ⟺ 当前 < 基线 − 容差，延迟回归 ⟺ 当前 > 基线 + 容差。
        gated: 要守的指标名集合，由当前领域包声明（无默认值——「守哪些」是域绑定的
            判断，给个全局默认正是此前静默降级的成因）。

    Returns:
        ``GateReport``：逐项 ``GateVerdict`` + ``passed`` + ``guarded_count``。
        基线有当前缺 → skipped；当前有基线缺 → new；二者皆不影响 passed。
    """
    base_metrics: dict[str, Any] = baseline.get("metrics", {})
    verdicts: list[GateVerdict] = []
    passed = True
    guarded = 0
    for name in gated:
        in_base = name in base_metrics
        cur = current.get(name)  # (value, is_latency) 或 None
        if in_base and cur is None:
            # 基线有、当前 N/A：无法比对（如槽位恒 N/A），不判对错。
            verdicts.append(
                GateVerdict(name=name, status="skipped",
                            baseline=base_metrics[name].get("value"),
                            is_latency=base_metrics[name].get("is_latency", False))
            )
            continue
        if not in_base and cur is not None:
            verdicts.append(
                GateVerdict(name=name, status="new", current=cur[0], is_latency=cur[1])
            )
            continue
        if not in_base and cur is None:
            # 基线、当前都没有：彻底无可比，跳过且不计入实守数（不产出噪声裁决）。
            continue
        # 两边都有：真正比对。
        base_val = base_metrics[name].get("value")
        cur_val, is_latency = cur  # type: ignore[misc]
        delta = cur_val - base_val
        if is_latency:
            regressed = cur_val > base_val + tolerance  # 延迟越大越差
        else:
            regressed = cur_val < base_val - tolerance  # 比率越小越差
        guarded += 1
        if regressed:
            passed = False
        verdicts.append(
            GateVerdict(
                name=name,
                status="regressed" if regressed else "ok",
                baseline=base_val,
                current=cur_val,
                delta=delta,
                is_latency=is_latency,
            )
        )
    return GateReport(verdicts=verdicts, passed=passed, guarded_count=guarded,
                      tolerance=tolerance)


def _fmt_gate_value(v: Optional[float], is_latency: bool) -> str:
    """门禁数值渲染：延迟为秒、比率为百分比。"""
    if v is None:
        return "—"
    return f"{v:.3f}s" if is_latency else f"{v * 100:.1f}%"


def format_gate_report(gate: GateReport) -> str:
    """渲染门禁结果：成功静默——回归/无法比对详列，通过项简列，末行给结论。"""
    lines = [f"\n回归门禁（容差 {gate.tolerance:.3f}）:"]
    for v in gate.verdicts:
        b = _fmt_gate_value(v.baseline, v.is_latency)
        c = _fmt_gate_value(v.current, v.is_latency)
        if v.status == "regressed":
            unit = "s" if v.is_latency else "pp"
            d = (v.delta or 0.0) * (1 if v.is_latency else 100)
            lines.append(f"  ✗ {v.name:14} 回归: 基线 {b} → 当前 {c}（Δ{d:+.1f}{unit}）")
        elif v.status == "skipped":
            lines.append(f"  – {v.name:14} 无法比对（本次 N/A；基线 {b}）")
        elif v.status == "new":
            lines.append(f"  + {v.name:14} 新增（基线无；当前 {c}）")
        else:  # ok
            lines.append(f"  ✓ {v.name:14} 基线 {b} → 当前 {c}")
    verdict = "PASS" if gate.passed else "FAIL"
    lines.append(f"\n门禁结论: {verdict}（实守 {gate.guarded_count} 项指标）")
    if not gate.passed:
        lines.append("  → 检测到回归，进程将以退出码 3 结束。")
    return "\n".join(lines)
