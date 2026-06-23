"""从导出的 span 还原「本次运行实际触发的有序工具序列」（评估采集层）。

纯函数、不触网、不依赖真实 provider，故可离线确定性单测。``run_evals.py`` 给每条用例
一个独立 ``InMemoryExporter`` 沙盒跑真 ``AgentLoop``，跑完把该 exporter 内**所有** span
交给本模块还原出有序工具序列，填进 ``EvalResult.actual_tools``。

设计要点（见 change evals-drive-agentloop-real-tools 的 design.md D2/D3）：
- **不按单一 trace_id 过滤**：C-lite 下子 Agent 内层 loop 各自开 root span（多棵断开的
  trace 树），按 trace_id 过滤会漏采子 Agent 的工具调用，故收集 exporter 内全部 span。
- **排序口径**：按 ``(span.start, span 内事件顺序)`` 还原全局顺序——span 内事件本就有序，
  跨 span 用开始时刻排序（同一 tracer 用同一单调 clock，故可比较）。
- **采全比松**：保留每次调用的 ``name`` 与 ``args``（有序），供后续改造做参数级/序列级比对；
  当前工具调用正确率指标只用其中的 name 集合。
- **默认剔除编排工具**：``delegate`` 是「派给哪个子 Agent」的编排动作、非领域工具，默认不计入
  ``actual_tools``（否则会污染与 ``expected_tools`` 的名字集合比对）。可经 ``exclude`` 调整。
"""

from __future__ import annotations

from typing import Any, Iterable

from harness.observability.span import Span

__all__ = ["collect_tool_calls", "DEFAULT_EXCLUDE"]

# 默认剔除的「编排型工具」名：delegate 只表达「派给谁」，不是被评估的领域工具。
DEFAULT_EXCLUDE = frozenset({"delegate"})


def collect_tool_calls(
    spans: Iterable[Span],
    exclude: Iterable[str] = DEFAULT_EXCLUDE,
) -> list[dict[str, Any]]:
    """从一组 span 还原有序的工具调用序列。

    Args:
        spans: 一次运行导出的全部 span（含子 Agent 各自的 root/step span）。
        exclude: 不计入结果的工具名集合（默认剔除编排工具 ``delegate``）。

    Returns:
        有序的 ``[{"name": str, "args": dict}, ...]``——按 ``(span.start, 事件顺序)`` 排列。
    """
    excluded = set(exclude)
    out: list[dict[str, Any]] = []
    # 跨 span 按开始时刻排序；span 内事件本就按发生顺序 append，故二者结合即全局顺序。
    for span in sorted(spans, key=lambda s: s.start):
        for event in span.events:
            if event.kind != "tool_call":
                continue
            name = event.payload.get("name", "")
            if name in excluded:
                continue
            # args 缺省成空 dict：采全（保留参数），但下游指标当前只用 name。
            out.append({"name": name, "args": event.payload.get("args") or {}})
    return out
