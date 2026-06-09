"""轻量 Span 模型（Phase 6 可观测层）。

不依赖任何第三方库——一次请求的每个 span 在内部就是这个 dataclass：
``trace_id`` 串联同一请求、``parent_id`` 指向上一层（root span 为 ``None``），
``events`` 顺序记录 thought / tool_call / observation 等，``attributes`` 挂
session_id / token 近似 / 工具名 等可检索字段。latency 由开始/结束时刻计算。

设计要点（design.md D1）：span 父子关系由我们显式持有（``parent_id``），不依赖
OpenTelemetry 的隐式 context 传播，故在手写 async 循环里也不会断树。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = ["Span", "SpanEvent"]


@dataclass
class SpanEvent:
    """span 上的一个时点事件，如 thought / tool_call / observation。"""

    kind: str
    payload: dict[str, Any]


@dataclass
class Span:
    """一次 trace 中的单个跨度。

    Attributes:
        trace_id: 同一请求内所有 span 共享，用于回放检索。
        span_id: 本 span 唯一标识。
        parent_id: 父 span 的 ``span_id``；root span 为 ``None``。
        name: span 名称（如 ``agent_loop.run`` / ``step``）。
        start: 开始时刻（来自注入的 monotonic clock，仅用于算 latency）。
        end: 结束时刻；``None`` 表示尚未结束。
        attributes: 可检索属性（session_id / token 近似 / 工具名 / 参数 等）。
        events: 顺序事件列表（thought / tool_call / observation ...）。
    """

    trace_id: str
    span_id: str
    parent_id: Optional[str]
    name: str
    start: float
    end: Optional[float] = None
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[SpanEvent] = field(default_factory=list)

    @property
    def latency(self) -> Optional[float]:
        """span 耗时（秒）；未结束时为 ``None``。"""
        if self.end is None:
            return None
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        """规整为可序列化字典（供 JSON 日志 exporter 与断言使用）。"""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "latency": self.latency,
            "attributes": dict(self.attributes),
            "events": [{"kind": e.kind, "payload": e.payload} for e in self.events],
        }
