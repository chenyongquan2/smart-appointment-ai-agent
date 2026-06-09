"""OTelSpanExporter 单测（Phase 6 可观测层）。

用 OTel ``InMemorySpanExporter`` 离线断言：内部 span → OTel span 的层级、duration
与 attributes 一致，全程不触网。另验证默认 JSON 日志路径不 import OpenTelemetry。
"""

import sys

import pytest

from harness.observability.tracer import Tracer


def _fake_clock(ticks):
    seq = iter(ticks)
    return lambda: next(seq)


def _counter_ids():
    n = {"i": 0}

    def factory():
        n["i"] += 1
        return f"id-{n['i']}"

    return factory


@pytest.fixture
def otel_memory():
    """构建接到 InMemorySpanExporter 的 provider，返回 (otel_tracer, memory)。"""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    provider = TracerProvider()
    memory = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    return provider.get_tracer("test"), memory


def test_internal_spans_map_to_otel_with_hierarchy_duration_attrs(otel_memory):
    from harness.observability.otel_exporter import OTelSpanExporter

    otel_tracer, memory = otel_memory
    exporter = OTelSpanExporter(otel_tracer=otel_tracer)
    # start(root)=0, start(child)=1, end(child)=3, end(root)=10
    tracer = Tracer(
        exporter,
        clock=_fake_clock([0.0, 1.0, 3.0, 10.0]),
        id_factory=_counter_ids(),
    )

    root = tracer.start_span("agent_loop.run", attributes={"session_id": "s1"})
    child = tracer.start_span("step", parent=root)
    tracer.add_tool_call(child, "find_technician", {"project": "肩颈"})
    tracer.set_tokens(child, 42)
    tracer.end_span(child)
    tracer.end_span(root)  # root 结束触发整条 trace 落地到 OTel

    finished = memory.get_finished_spans()
    by_name = {s.name: s for s in finished}
    assert set(by_name) == {"agent_loop.run", "step"}

    otel_root = by_name["agent_loop.run"]
    otel_child = by_name["step"]

    # duration（ns）== 内部 latency：root 10s、child 2s。
    assert otel_root.end_time - otel_root.start_time == 10_000_000_000
    assert otel_child.end_time - otel_child.start_time == 2_000_000_000

    # 层级：child.parent 指向 root 的 span context。
    assert otel_child.parent is not None
    assert otel_child.parent.span_id == otel_root.context.span_id
    assert otel_root.parent is None

    # attributes：session_id / tokens / tool_name / tool_args。
    assert otel_root.attributes["session_id"] == "s1"
    assert otel_child.attributes["tokens"] == 42
    assert otel_child.attributes["tokens_approximate"] is True
    assert otel_child.attributes["tool_name"] == "find_technician"
    assert "肩颈" in otel_child.attributes["tool_args"]


def test_default_logging_path_does_not_import_opentelemetry():
    """默认 JSON 日志 exporter 路径不得 import OpenTelemetry（design.md D6）。"""
    # 剔除已加载的 otel 与本包，重新只 import 默认路径所需模块。
    for name in list(sys.modules):
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            del sys.modules[name]
    for name in list(sys.modules):
        if name.startswith("harness.observability"):
            del sys.modules[name]

    import harness.observability  # noqa: F401  —— 包入口
    from harness.observability.logging_exporter import LoggingSpanExporter  # noqa: F401
    from harness.observability.tracer import Tracer  # noqa: F401

    assert not any(
        n == "opentelemetry" or n.startswith("opentelemetry.") for n in sys.modules
    ), "默认路径不应 import opentelemetry"
