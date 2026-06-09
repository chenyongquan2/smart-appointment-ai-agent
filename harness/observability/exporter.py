"""SpanExporter 协议与测试用收集器（Phase 6 可观测层）。

``Tracer`` 的输出经 ``SpanExporter`` 协议解耦：span 结束时调用 ``export(span)``，
后端可替换（JSON 日志 / OpenTelemetry / 测试收集器）而不改动循环与业务代码
（design.md D1 可插点）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from harness.observability.span import Span

__all__ = ["SpanExporter", "InMemoryExporter"]


@runtime_checkable
class SpanExporter(Protocol):
    """span 输出后端协议。实现 ``export`` 即可被 ``Tracer`` 使用。"""

    def export(self, span: Span) -> None:
        """导出一个已结束的 span（同步、不得抛出以免影响主流程）。"""
        ...


class InMemoryExporter:
    """把导出的 span 收进内存列表，供单元测试断言（不触网、确定性）。"""

    def __init__(self) -> None:
        self.spans: list[Span] = []

    def export(self, span: Span) -> None:
        self.spans.append(span)

    # —— 测试便捷查询 ——
    def by_trace(self, trace_id: str) -> list[Span]:
        """取某 trace 的全部 span（按导出顺序）。"""
        return [s for s in self.spans if s.trace_id == trace_id]

    def roots(self) -> list[Span]:
        """取全部 root span（``parent_id`` 为 None）。"""
        return [s for s in self.spans if s.parent_id is None]

    def children_of(self, span: Span) -> list[Span]:
        """取某 span 的直接子 span。"""
        return [s for s in self.spans if s.parent_id == span.span_id]
