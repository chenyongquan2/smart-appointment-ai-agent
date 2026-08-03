"""从 span 检出「疑似坏」客观信号（改造 7 · 在线评估闭环）。

纯函数、不触网、不调 LLM——给定一组 span 即可确定地得出命中的信号标签。放在 ``harness/``
层（而非 ``evals/``）是为让**采样 exporter**（错误优先留存）与 ``evals/triage.py``（半自动
甄别）复用同一套判定，且不违反「evals 依赖 harness、不反向」的分层。

信号口径**逐条对照 ``AgentLoop`` 的真实落点**（见 harness/runtime/agent_loop.py）：

- ``guardrail_exhausted`` / ``spin_detected``：loop 在 ``add_event(step,"error",{"type":...})`` 记的 error 事件。
- ``tool_failure``：``_dispatch`` 把工具异常吞成 ``tool_failure_message(...)`` 作为 observation
  结果回灌；**以及**工具正常返回但结果带非超时的 ``error_kind``（见下）。
- ``tool_timeout``：``_dispatch`` 的 ``asyncio.wait_for`` 掐断（``tool_timeout_message(...)``）；
  **以及**工具正常返回但结果带 ``error_kind == "timeout"``（service 自己分类的超时，loop
  层面完全没有异常）。
- ``max_steps_reached``：跑满步数（或预算耗尽）而未产出终态回复——结构化判定：最后一个 step
  仍含 ``tool_call`` 事件（正常终态回复的那一步无工具调用），且全程无 error 事件。
- ``repeated_tool_identity``：同一 ``(工具, 身份参数)`` 组合出现在 ≥N 个步骤中（缺省 3）——
  即「同一个动作被反复执行，只有宽度旋钮在变」。⚠ **纯观测信号：它不终止循环**，与护栏
  产生的 ``spin_detected`` 是两回事（后者会终止）。身份参数由 ``AgentLoop`` 在记录时按
  ``Tool.breadth_args`` 算好，本模块只读结构、**不含任何参数名白名单**。

> ⚠ 曾经的失真，记下来免得重演：
> 1. 本模块的 docstring 原写「**严格**对齐真实落点」，实际只对齐了两个落点里的一个——
>    超时支从 ``except Exception`` 拆出去后，"工具执行超时"这句话不匹配"工具执行失败"
>    前缀，于是超时**静默不再命中**。真实群聊里「连吃三次 60 秒超时、白等 3 分钟」在
>    triage 里报 0 个候选。文案现由 ``harness/tool_outcome.py`` 单一持有，两侧同源。
> 2. ``[ERROR]`` 回复前缀是**遗留 agents/ 路径**的产物（agent_router/classification_processor），
>    当前生产走的 harness ``AgentLoop`` 只产 ``[REPLY]``（含兜底），故不在本判定内。
>    ``observability`` 与 ``bad-case-feedback`` 两份 spec 原把它列为必须信号——那是**规格
>    要求了一个实现刻意不做的信号**，已在本 change 里按真实落点重述，不臆造信号。

**为何 ``tool_timeout`` 与 ``tool_failure`` 分开而不合并**：补救动作不同——超时该**收窄**
查询，普通失败通常是参数错或下游报错。合并会让 triage 的候选失去可操作性。

**为何只认 ``error_kind`` 一个键、不泛化成「任何错误类字段」**：``services/repo.py`` 用
``status`` 表达结果，且 ``need_clone`` / ``branch_not_found`` / ``bad_env`` / ``need_git_url``
被**显式定义为正常引导状态**（``GUIDE_STATUS``，``ok`` 属性就是 ``status in GUIDE_STATUS``）。
泛化判定会把"仓库还没备好、请运维 clone"变成疑似坏候选——triage 的价值全在信噪比，误报
比漏报更能毁掉它。``error_kind`` 之所以安全，是因为它在 ``services/vlog.py`` 里**只在超时
与异常分类两条真失败路径上被赋值**。
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from harness.observability.span import Span

# ★ 前缀从 harness/tool_outcome.py 导入而非本地重写字面量：那次静默断开的根因正是
#   同一句文案在两个模块各存一份。再导出（__all__ 含它）以免打断既有 import 方。
from harness.tool_outcome import TOOL_FAILURE_PREFIX, TOOL_TIMEOUT_PREFIX

__all__ = [
    "detect_bad_signals",
    "is_bad_trace",
    "TOOL_FAILURE_PREFIX",
    "TOOL_TIMEOUT_PREFIX",
    "TIMEOUT_ERROR_KIND",
    "DEFAULT_REPEAT_IDENTITY_STEPS",
]

# service 层自行分类出的「超时」取值（``services/vlog.py`` 的 ``classify_error`` 口径）。
# 其它非空取值（connect_failed / http_error / other）同属真失败，归 ``tool_failure``。
TIMEOUT_ERROR_KIND = "timeout"

# 同一 (工具, 身份参数) 组合出现在多少个**步骤**中即判「换参重复」。
# 缺省 3：真实数据上 3 命中 2/3 病态且对三种正当模式 0 误报；调到 4 会漏掉那条只有
# 3 步的真实坏 case（term 固定、window 2d→30m→7d）。攒到更多真实流量后按误报率复核。
DEFAULT_REPEAT_IDENTITY_STEPS = 3


def _identity_key(event_payload: dict[str, Any]) -> Optional[tuple[str, str]]:
    """从 tool_call 事件取 ``(工具名, 身份参数)`` 键；无 ``identity`` 字段时返回 ``None``。

    ``identity`` 由 ``AgentLoop`` 在记录时算好（见 ``Tracer.add_tool_call``）。本函数
    **绝不自行推断哪些参数属宽度类**——那需要参数名白名单，等于把域内容嵌进域无关运行时。
    故本 change 之前落的 trace（payload 无该字段）不会命中此信号，如实接受。
    """
    identity = event_payload.get("identity")
    if not isinstance(identity, dict):
        return None
    name = str(event_payload.get("name") or "")
    # sort_keys 让键序不影响相等性（与 guardrails._signature 同口径）。
    return (name, json.dumps(identity, sort_keys=True, ensure_ascii=False, default=str))


def _repeated_identity_steps(steps: list[Span], threshold: int) -> bool:
    """同一 ``(工具名, 身份参数)`` 是否出现在 ≥threshold 个**步骤**中。

    两条口径都是被真实数据逼出来的（见 change ``detect-repeated-tool-identity`` design D1）：

    - **按步骤去重计数**（同一步内并行调多次同一工具只计 1）：否则「多意图并行检索」
      一步就能顶到阈值，正当模式直接变误报。
    - **不要求连续**：真实的病态模式中间会夹别的工具（``load_reference`` 插在两次
      ``vlog_query`` 之间），要求连续就漏。这也是为什么本判定不是改 ``_signature``
      能解决的——「连续整步签名相同」那个形状在真实数据上抓到病态 0/3。
    """
    per_identity: dict[tuple[str, str], int] = {}
    for s in steps:
        seen_in_step = set()
        for e in s.events:
            if e.kind != "tool_call":
                continue
            key = _identity_key(e.payload)
            if key is not None:
                seen_in_step.add(key)
        for key in seen_in_step:  # 一步内同一身份只累加一次
            per_identity[key] = per_identity.get(key, 0) + 1
    return any(n >= threshold for n in per_identity.values())


def detect_bad_signals(
    spans: Iterable[Span], repeat_identity_steps: int = DEFAULT_REPEAT_IDENTITY_STEPS
) -> list[str]:
    """从一组 span（通常是同一 trace_id 的一次运行）检出命中的「疑似坏」信号标签。

    Args:
        repeat_identity_steps: 判 ``repeated_tool_identity`` 的步骤数阈值（见该常量说明）。

    Returns:
        去重且有序的信号标签列表；无任何信号时为空列表（即「看起来正常」）。
    """
    spans = list(spans)
    error_types: set[str] = set()
    tool_failure = False
    tool_timeout = False
    steps: list[Span] = []

    for s in spans:
        if s.name == "step":
            steps.append(s)
        for e in s.events:
            if e.kind == "error":
                error_types.add(str(e.payload.get("type") or "error"))
            elif e.kind == "observation":
                result = str(e.payload.get("result", ""))
                # ① loop 级：_dispatch 把超时/异常吞成一句话回灌，按前缀认。
                #    两个分支互斥（同一句话不可能既是超时又是失败）。
                if result.startswith(TOOL_TIMEOUT_PREFIX):
                    tool_timeout = True
                elif result.startswith(TOOL_FAILURE_PREFIX):
                    tool_failure = True
                # ② service 级：工具**正常返回**但结果对象带错误分类字段。
                #    读结构化的 error_kind（由 Tracer.add_observation 在 str() 化之前提取），
                #    绝不对 str(dict) 做子串匹配——那排版不是契约。
                error_kind = e.payload.get("error_kind")
                if isinstance(error_kind, str) and error_kind:
                    if error_kind == TIMEOUT_ERROR_KIND:
                        tool_timeout = True
                    else:
                        tool_failure = True

    signals: list[str] = sorted(error_types)
    if tool_failure:
        signals.append("tool_failure")
    if tool_timeout:
        signals.append("tool_timeout")
    # 「同一动作被反复执行」。★ 刻意不叫 spin_*：``spin_detected`` 是**护栏**产生的 error
    #   事件（它会终止循环），本信号只做观测、循环行为一行不变。名字混起来会让人误以为
    #   护栏已经拦住了。
    if _repeated_identity_steps(steps, repeat_identity_steps):
        signals.append("repeated_tool_identity")

    # 跑满步数/预算耗尽：仅在「无 error 事件」时才据结构判（有 error 已被上面捕获，避免重复归因）。
    if not error_types and steps:
        steps.sort(key=lambda s: s.start)  # 同一 tracer 单调 clock，可比较；取最后一步
        if any(e.kind == "tool_call" for e in steps[-1].events):
            signals.append("max_steps_reached")

    return signals


def is_bad_trace(spans: Iterable[Span]) -> bool:
    """该组 span 是否命中任一「疑似坏」信号（供采样 exporter 的错误优先留存判定）。"""
    return bool(detect_bad_signals(spans))
