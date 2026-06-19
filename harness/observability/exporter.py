"""SpanExporter 协议与测试用收集器（Phase 6 可观测层）。

``Tracer`` 的输出经 ``SpanExporter`` 协议解耦：span 结束时调用 ``export(span)``，
后端可替换（JSON 日志 / OpenTelemetry / 测试收集器）而不改动循环与业务代码
（design.md D1 可插点）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from harness.observability.span import Span

__all__ = ["SpanExporter", "InMemoryExporter"]


# ★ 用 Protocol（结构化类型）而非抽象基类：任何「长得像」——即有 export(span) 方法
#   ——的对象都算 SpanExporter，无需显式继承。这正是 Tracer 既能打日志又能发 OTel
#   还能进内存收集器的根基：同一个 Tracer 不认后端的「血统」，只认这一个方法。
# runtime_checkable 让 isinstance(obj, SpanExporter) 在运行时也能用（仅查方法是否存在）。
@runtime_checkable
class SpanExporter(Protocol):
    """span 输出后端协议。实现 ``export`` 即可被 ``Tracer`` 使用。"""

    def export(self, span: Span) -> None:
        """导出一个已结束的 span（同步、不得抛出以免影响主流程）。"""
        ...  # Protocol 方法体只是占位「签名声明」，没有实现——实现交给各后端类


class InMemoryExporter:
    """把导出的 span 收进内存列表，供单元测试断言（不触网、确定性）。"""

    # 注意：它并不 import 或继承 SpanExporter，但因为有 export(span) 方法，
    # 按上面的 Protocol 规则它「就是」一个合法 exporter（鸭子类型 / 结构化类型）。

    def __init__(self) -> None:
        self.spans: list[Span] = []  # 所有导出过的 span 按到达顺序存这里

    def export(self, span: Span) -> None:
        self.spans.append(span)  # 不写日志、不发网络，纯进内存——测试拿它做断言最省心

    # —— 测试便捷查询（下面三个都是对 self.spans 做简单过滤，方便断言 span 树）——
    def by_trace(self, trace_id: str) -> list[Span]:
        """取某 trace 的全部 span（按导出顺序）。"""
        return [s for s in self.spans if s.trace_id == trace_id]

    def roots(self) -> list[Span]:
        """取全部 root span（``parent_id`` 为 None）。"""
        return [s for s in self.spans if s.parent_id is None]  # 无父者即每条 trace 的根

    def children_of(self, span: Span) -> list[Span]:
        """取某 span 的直接子 span。"""
        # 子的判定：它的 parent_id 等于本 span 的 span_id（与 Tracer.start_span 里
        # parent_id=parent.span_id 的写法严丝合缝对应）。
        return [s for s in self.spans if s.parent_id == span.span_id]
