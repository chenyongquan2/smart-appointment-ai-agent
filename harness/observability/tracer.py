"""Tracer：开关 span、记录事件、结束时导出（Phase 6 可观测层）。

一次请求的用法（见 agent_loop 接入）::

    tracer = Tracer(exporter)
    root = tracer.start_span("agent_loop.run", attributes={"session_id": sid})
    for step in ...:
        step_span = tracer.start_span("step", parent=root)
        tracer.add_thought(step_span, ai_text)
        tracer.add_tool_call(step_span, name, args)
        tracer.add_observation(step_span, name, result)
        tracer.set_tokens(step_span, n_approx)
        tracer.end_span(step_span)
    tracer.end_span(root)

设计要点（design.md D1/D3）：
- 父子关系由 ``parent`` 显式传入，``trace_id`` 由 root 生成、child 继承——不依赖
  OpenTelemetry 隐式 context，手写 async 循环里不会断树。
- ``clock`` 与 ``id_factory`` 可注入，使 latency 与 id 在单测中确定性可断言。
- token 记为近似（``approximate=True``），复用 guardrails 的 ``estimate_tokens`` 口径。

``NoopTracer`` 实现同样接口但什么都不做，供 ``AgentLoop`` 在未注入 tracer 时退化
（向后兼容，design.md D2）。
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Optional

from harness.observability.exporter import SpanExporter
from harness.observability.span import Span, SpanEvent

__all__ = ["Tracer", "NoopTracer"]


class Tracer:
    """开/关 span 并在结束时经 exporter 导出。

    Args:
        exporter: span 输出后端（实现 ``SpanExporter.export``）。
        clock: 单调时钟，仅用于算 latency；默认 ``time.perf_counter``，测试可注入。
        id_factory: 生成 trace_id/span_id 的工厂；默认 uuid4 十六进制，测试可注入
            计数器以获得确定性 id。
    """

    def __init__(
        self,
        exporter: SpanExporter,
        clock: Optional[Callable[[], float]] = None,
        id_factory: Optional[Callable[[], str]] = None,
    ) -> None:
        self._exporter = exporter
        self._clock = clock or time.perf_counter
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    def start_span(
        self,
        name: str,
        parent: Optional[Span] = None,
        attributes: Optional[dict[str, Any]] = None,
    ) -> Span:
        """开一个 span。无 ``parent`` 即 root（生成新 trace_id）；有则继承 trace_id。"""
        trace_id = parent.trace_id if parent is not None else self._id_factory()
        return Span(
            trace_id=trace_id,
            span_id=self._id_factory(),
            parent_id=parent.span_id if parent is not None else None,
            name=name,
            start=self._clock(),
            attributes=dict(attributes or {}),
        )

    def end_span(self, span: Span) -> None:
        """结束 span（记结束时刻）并导出。导出异常被吞掉，绝不影响主流程。"""
        span.end = self._clock()
        try:
            self._exporter.export(span)
        except Exception:  # noqa: BLE001 —— 可观测不得拖垮业务主流程
            pass

    # —— 事件记录便捷方法 ——
    def add_event(self, span: Span, kind: str, payload: dict[str, Any]) -> None:
        span.events.append(SpanEvent(kind=kind, payload=payload))

    def add_thought(self, span: Span, text: str) -> None:
        """记录该步 LLM 产出的文本/决策。"""
        self.add_event(span, "thought", {"text": text})

    def add_tool_call(self, span: Span, name: str, args: Any) -> None:
        """记录一次工具调用（名称 + 参数）。"""
        self.add_event(span, "tool_call", {"name": name, "args": args})
        # 同时挂到 attributes 便于检索/给 OTel span 当属性。
        span.attributes.setdefault("tool_name", name)

    def add_observation(self, span: Span, name: str, result: Any) -> None:
        """记录工具结果。"""
        self.add_event(span, "observation", {"name": name, "result": str(result)})

    def set_tokens(self, span: Span, tokens: int, approximate: bool = True) -> None:
        """记录该 span 的 token（近似值，标注 approximate）。"""
        span.attributes["tokens"] = tokens
        span.attributes["tokens_approximate"] = approximate


class NoopTracer(Tracer):
    """什么都不做的 tracer：``AgentLoop`` 未注入 tracer 时退化使用（向后兼容）。

    复用 ``Tracer`` 的 span 构造逻辑（便于调用方拿到 span 对象做父子传参），但
    ``end_span`` 不导出、事件方法被覆盖为 no-op，故不产生任何输出、零副作用。
    """

    def __init__(self) -> None:
        # 不需要真实 exporter；导出已被 end_span 覆盖为 no-op。
        super().__init__(exporter=_NULL_EXPORTER)

    def end_span(self, span: Span) -> None:  # noqa: D401 —— 覆盖为 no-op
        span.end = self._clock()

    def add_event(self, span: Span, kind: str, payload: dict[str, Any]) -> None:
        pass

    def set_tokens(self, span: Span, tokens: int, approximate: bool = True) -> None:
        pass


class _NullExporter:
    def export(self, span: Span) -> None:  # pragma: no cover - 永不被调用
        pass


_NULL_EXPORTER = _NullExporter()
