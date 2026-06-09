"""可选 OpenTelemetry SpanExporter（Phase 6 可观测层）。

把内部 :class:`~harness.observability.span.Span` 映射为 OTel span：root/child 层级
一致、``duration`` 取自内部 latency、``attributes`` 含 token 近似 / 工具名 / 参数。
可对接 OTel ``InMemorySpanExporter`` 在单测中离线断言，全程不触网。

隔离要求（design.md D6）：OpenTelemetry 仅在本模块、且仅当**启用**该 exporter 时
才需要——其 import 在 ``__init__`` 内进行，缺失时抛清晰错误；包的 ``__init__`` 不
导入本模块，故默认 JSON 日志路径不会 import OTel。

子 span 先于父 span 结束（root 最后结束），故按 trace 缓冲，待 root 到达再统一
按"父先于子"的顺序构建 OTel span，从而正确重建父子上下文（不依赖 OTel 隐式 context）。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from harness.observability.span import Span

__all__ = ["OTelSpanExporter"]


class OTelSpanExporter:
    """内部 span → OpenTelemetry span 的 exporter。

    Args:
        otel_tracer: 可选的 OTel ``Tracer``；缺省时取全局 tracer。测试可传入接到
            ``InMemorySpanExporter`` 的 provider 所得 tracer，以离线断言。
    """

    def __init__(self, otel_tracer: Optional[Any] = None) -> None:
        try:
            from opentelemetry import trace
            from opentelemetry.trace import set_span_in_context
        except ImportError as exc:  # pragma: no cover - 仅在缺依赖时触发
            raise RuntimeError(
                "启用 OTelSpanExporter 需安装 opentelemetry-sdk（uv add opentelemetry-sdk）"
            ) from exc

        self._set_span_in_context = set_span_in_context
        self._otel_tracer = otel_tracer or trace.get_tracer("harness.observability")
        self._buffer: dict[str, list[Span]] = {}

    def export(self, span: Span) -> None:
        """缓冲 span；当 root（``parent_id`` 为 None）到达时整条 trace 一次性落地。"""
        self._buffer.setdefault(span.trace_id, []).append(span)
        if span.parent_id is None:
            self._flush(span.trace_id)

    def _flush(self, trace_id: str) -> None:
        spans = self._buffer.pop(trace_id, [])
        ordered = _parents_before_children(spans)

        created: dict[str, Any] = {}
        for s in ordered:
            parent_otel = created.get(s.parent_id) if s.parent_id else None
            context = self._set_span_in_context(parent_otel) if parent_otel else None
            otel_span = self._otel_tracer.start_span(
                s.name,
                context=context,
                start_time=_to_ns(s.start),
            )
            self._apply_attributes(otel_span, s)
            created[s.span_id] = otel_span

        # 结束（end 触发 SimpleSpanProcessor 导出）；end_time 用内部结束时刻，
        # 使 OTel duration == 内部 latency。
        for s in ordered:
            end = s.end if s.end is not None else s.start
            created[s.span_id].end(end_time=_to_ns(end))

    def _apply_attributes(self, otel_span: Any, s: Span) -> None:
        # 原始属性中的标量直接搬运（OTel 属性仅接受标量/标量序列）。
        for key, value in s.attributes.items():
            if isinstance(value, (str, bool, int, float)):
                otel_span.set_attribute(key, value)
        # 工具参数（dict）序列化为 JSON 字符串作为属性。
        for event in s.events:
            if event.kind == "tool_call":
                otel_span.set_attribute(
                    "tool_args",
                    json.dumps(event.payload.get("args"), ensure_ascii=False, default=str),
                )


def _to_ns(seconds: float) -> int:
    """秒（来自内部单调时钟）→ 纳秒整数（OTel start_time/end_time 口径）。"""
    return int(seconds * 1_000_000_000)


def _parents_before_children(spans: list[Span]) -> list[Span]:
    """稳定拓扑排序：父 span 一定排在其子 span 之前。"""
    placed: set[str] = set()
    ordered: list[Span] = []
    pending = list(spans)
    # 最多迭代 len 轮即可收敛（层级深度 ≤ 节点数）。
    while pending:
        progressed = False
        rest: list[Span] = []
        for s in pending:
            if s.parent_id is None or s.parent_id in placed:
                ordered.append(s)
                placed.add(s.span_id)
                progressed = True
            else:
                rest.append(s)
        pending = rest
        if not progressed:
            # 父不在本批（理论上不应发生）：兜底追加，避免死循环。
            ordered.extend(pending)
            break
    return ordered
