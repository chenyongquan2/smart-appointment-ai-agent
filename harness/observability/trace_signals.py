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

from typing import Iterable

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
]

# service 层自行分类出的「超时」取值（``services/vlog.py`` 的 ``classify_error`` 口径）。
# 其它非空取值（connect_failed / http_error / other）同属真失败，归 ``tool_failure``。
TIMEOUT_ERROR_KIND = "timeout"


def detect_bad_signals(spans: Iterable[Span]) -> list[str]:
    """从一组 span（通常是同一 trace_id 的一次运行）检出命中的「疑似坏」信号标签。

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

    # 跑满步数/预算耗尽：仅在「无 error 事件」时才据结构判（有 error 已被上面捕获，避免重复归因）。
    if not error_types and steps:
        steps.sort(key=lambda s: s.start)  # 同一 tracer 单调 clock，可比较；取最后一步
        if any(e.kind == "tool_call" for e in steps[-1].events):
            signals.append("max_steps_reached")

    return signals


def is_bad_trace(spans: Iterable[Span]) -> bool:
    """该组 span 是否命中任一「疑似坏」信号（供采样 exporter 的错误优先留存判定）。"""
    return bool(detect_bad_signals(spans))
