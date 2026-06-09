"""harness 可观测层（Phase 6）。

把一次 ``AgentLoop`` 请求建模为一条带 ``trace_id`` 的 trace：整次 run 一个 root span、
循环每步一个 child span，记录 thought / tool_call / observation / latency / tokens。
输出经可插 ``SpanExporter`` 解耦——默认 JSON 日志 exporter（零额外依赖），可选
OpenTelemetry exporter（离线用 ``InMemorySpanExporter`` 断言）。

设计要点见 openspec change phase-6-observability 的 design.md（D1 自研 tracer + 可插
exporter，OTel 仅作为其中一个 exporter）。
"""

from harness.observability.exporter import InMemoryExporter, SpanExporter
from harness.observability.span import Span
from harness.observability.tracer import NoopTracer, Tracer

__all__ = [
    "Span",
    "SpanExporter",
    "InMemoryExporter",
    "Tracer",
    "NoopTracer",
]
