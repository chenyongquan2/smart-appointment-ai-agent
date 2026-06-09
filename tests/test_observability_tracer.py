"""Tracer / Span / Exporter 单测（Phase 6 可观测层）。

全程离线确定性：注入计数器 id_factory 与可控 clock，断言 trace_id 串联、root+child
层级、latency、token 近似标注与 thought/tool_call/observation 事件落点。
"""

from harness.observability.exporter import InMemoryExporter
from harness.observability.logging_exporter import LoggingSpanExporter
from harness.observability.tracer import NoopTracer, Tracer


def _counter_ids():
    """确定性 id 工厂：id-1, id-2, ...（每次 start_span 取一个）。"""
    n = {"i": 0}

    def factory() -> str:
        n["i"] += 1
        return f"id-{n['i']}"

    return factory


def _fake_clock(ticks):
    """按预设序列返回时刻，便于断言 latency。"""
    seq = iter(ticks)

    def clock() -> float:
        return next(seq)

    return clock


def test_root_and_child_share_trace_and_link_parent():
    exporter = InMemoryExporter()
    # start(root)=0, start(child)=1, end(child)=3, end(root)=10
    tracer = Tracer(
        exporter,
        clock=_fake_clock([0.0, 1.0, 3.0, 10.0]),
        id_factory=_counter_ids(),
    )

    root = tracer.start_span("agent_loop.run", attributes={"session_id": "s1"})
    child = tracer.start_span("step", parent=root)
    tracer.end_span(child)
    tracer.end_span(root)

    # trace_id 串联：root 生成 id-1（trace_id）+ id-2（span_id），child 继承 trace_id。
    assert child.trace_id == root.trace_id
    assert child.parent_id == root.span_id
    assert root.parent_id is None
    # 导出顺序：child 先结束先导出，再 root。
    assert [s.name for s in exporter.spans] == ["step", "agent_loop.run"]
    assert exporter.children_of(root) == [child]
    assert exporter.roots() == [root]


def test_latency_from_injected_clock():
    exporter = InMemoryExporter()
    tracer = Tracer(exporter, clock=_fake_clock([0.0, 2.5]), id_factory=_counter_ids())

    span = tracer.start_span("step")
    assert span.latency is None  # 未结束
    tracer.end_span(span)

    assert span.latency == 2.5


def test_records_thought_tool_call_observation_and_token_approx():
    exporter = InMemoryExporter()
    tracer = Tracer(exporter, clock=_fake_clock([0.0, 1.0]), id_factory=_counter_ids())

    span = tracer.start_span("step")
    tracer.add_thought(span, "我需要先查技师")
    tracer.add_tool_call(span, "find_technician", {"project": "肩颈"})
    tracer.add_observation(span, "find_technician", ["张三"])
    tracer.set_tokens(span, 42)
    tracer.end_span(span)

    kinds = [e.kind for e in span.events]
    assert kinds == ["thought", "tool_call", "observation"]
    assert span.events[0].payload == {"text": "我需要先查技师"}
    assert span.events[1].payload == {"name": "find_technician", "args": {"project": "肩颈"}}
    assert span.attributes["tool_name"] == "find_technician"
    assert span.attributes["tokens"] == 42
    assert span.attributes["tokens_approximate"] is True


def test_to_dict_is_json_serializable_shape():
    exporter = InMemoryExporter()
    tracer = Tracer(exporter, clock=_fake_clock([0.0, 1.0]), id_factory=_counter_ids())
    span = tracer.start_span("step", attributes={"session_id": "s1"})
    tracer.add_thought(span, "hi")
    tracer.end_span(span)

    d = span.to_dict()
    assert d["trace_id"] and d["span_id"]
    assert d["latency"] == 1.0
    assert d["attributes"]["session_id"] == "s1"
    assert d["events"][0]["kind"] == "thought"


def test_exporter_failure_does_not_propagate():
    class Boom:
        def export(self, span):
            raise RuntimeError("exporter down")

    tracer = Tracer(Boom(), clock=_fake_clock([0.0, 1.0]), id_factory=_counter_ids())
    span = tracer.start_span("step")
    # end_span 必须吞掉 exporter 异常，不冒泡。
    tracer.end_span(span)
    assert span.latency == 1.0


def test_logging_exporter_emits_single_json_line(caplog):
    import logging

    exporter = LoggingSpanExporter(logging.getLogger("harness.observability.test"))
    tracer = Tracer(exporter, clock=_fake_clock([0.0, 1.0]), id_factory=_counter_ids())

    with caplog.at_level(logging.INFO, logger="harness.observability.test"):
        span = tracer.start_span("step", attributes={"session_id": "s1"})
        tracer.add_thought(span, "hi")
        tracer.end_span(span)

    assert any('"event": "span"' in rec.getMessage() for rec in caplog.records)


def test_noop_tracer_produces_no_output_but_supports_parenting():
    tracer = NoopTracer()
    root = tracer.start_span("agent_loop.run")
    child = tracer.start_span("step", parent=root)
    tracer.add_thought(child, "ignored")
    tracer.set_tokens(child, 99)
    tracer.end_span(child)
    tracer.end_span(root)

    # 仍能拿到 span 对象与父子关系（供调用方传参），但不记录事件、不导出。
    assert child.parent_id == root.span_id
    assert child.events == []
    assert "tokens" not in child.attributes
