"""从 span 检出「疑似坏」客观信号（改造 7 · 在线评估闭环）。

纯函数、不触网、不调 LLM——给定一组 span 即可确定地得出命中的信号标签。放在 ``harness/``
层（而非 ``evals/``）是为让**采样 exporter**（错误优先留存）与 ``evals/triage.py``（半自动
甄别）复用同一套判定，且不违反「evals 依赖 harness、不反向」的分层。

信号口径**严格对齐 ``AgentLoop`` 的真实落点**（见 harness/runtime/agent_loop.py）：
- ``guardrail_exhausted`` / ``spin_detected``：loop 在 ``add_event(step,"error",{"type":...})`` 记的 error 事件。
- ``tool_failure``：``_dispatch`` 把工具异常吞成 ``"工具执行失败（…）：…"`` 作为 observation 结果回灌。
- ``max_steps_reached``：跑满步数（或预算耗尽）而未产出终态回复——结构化判定：最后一个 step
  仍含 ``tool_call`` 事件（正常终态回复的那一步无工具调用），且全程无 error 事件。

> 注：``[ERROR]`` 回复前缀是**遗留 agents/ 路径**的产物（agent_router/classification_processor），
> 当前生产走的 harness ``AgentLoop`` 只产 ``[REPLY]``（含兜底），故不在本判定内——诚实标注、不臆造信号。
"""

from __future__ import annotations

from typing import Iterable

from harness.observability.span import Span

__all__ = ["detect_bad_signals", "is_bad_trace", "TOOL_FAILURE_PREFIX"]

# 与 AgentLoop._dispatch 的错误回灌文案前缀一致（工具异常被吞成这句当 observation 喂回）。
TOOL_FAILURE_PREFIX = "工具执行失败"


def detect_bad_signals(spans: Iterable[Span]) -> list[str]:
    """从一组 span（通常是同一 trace_id 的一次运行）检出命中的「疑似坏」信号标签。

    Returns:
        去重且有序的信号标签列表；无任何信号时为空列表（即「看起来正常」）。
    """
    spans = list(spans)
    error_types: set[str] = set()
    tool_failure = False
    steps: list[Span] = []

    for s in spans:
        if s.name == "step":
            steps.append(s)
        for e in s.events:
            if e.kind == "error":
                error_types.add(str(e.payload.get("type") or "error"))
            elif e.kind == "observation":
                if str(e.payload.get("result", "")).startswith(TOOL_FAILURE_PREFIX):
                    tool_failure = True

    signals: list[str] = sorted(error_types)
    if tool_failure:
        signals.append("tool_failure")

    # 跑满步数/预算耗尽：仅在「无 error 事件」时才据结构判（有 error 已被上面捕获，避免重复归因）。
    if not error_types and steps:
        steps.sort(key=lambda s: s.start)  # 同一 tracer 单调 clock，可比较；取最后一步
        if any(e.kind == "tool_call" for e in steps[-1].events):
            signals.append("max_steps_reached")

    return signals


def is_bad_trace(spans: Iterable[Span]) -> bool:
    """该组 span 是否命中任一「疑似坏」信号（供采样 exporter 的错误优先留存判定）。"""
    return bool(detect_bad_signals(spans))
