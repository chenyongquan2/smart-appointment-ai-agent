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


# ── 墙钟时间戳（change: fix-trace-triage-blindspots）────────────────────────
def _fixed_wall_clock(iso: str):
    """确定性墙钟：始终返回同一时刻，便于精确断言。"""
    from datetime import datetime

    dt = datetime.fromisoformat(iso)
    return lambda: dt


def test_wall_clock_is_injectable_and_lands_in_to_dict():
    """墙钟可注入 → started_at 确定可断言，且进 to_dict（落盘后才能按日期切窗）。"""
    exporter = InMemoryExporter()
    tracer = Tracer(
        exporter,
        clock=_fake_clock([10.0, 12.5]),
        id_factory=_counter_ids(),
        wall_clock=_fixed_wall_clock("2026-08-03T10:00:00+00:00"),
    )

    span = tracer.start_span("agent_loop.run")
    tracer.end_span(span)

    assert span.started_at == "2026-08-03T10:00:00+00:00"
    assert exporter.spans[0].to_dict()["started_at"] == "2026-08-03T10:00:00+00:00"


def test_wall_clock_and_monotonic_clock_do_not_interfere():
    """两套时间各司其职：latency 仍由单调 clock 算，墙钟只定位时间点。

    刻意不合并成一个字段——把 start 改成墙钟会在系统时间回拨时算出负耗时。
    """
    tracer = Tracer(
        InMemoryExporter(),
        clock=_fake_clock([10.0, 12.5]),
        id_factory=_counter_ids(),
        wall_clock=_fixed_wall_clock("2026-08-03T10:00:00+00:00"),
    )

    span = tracer.start_span("step")
    tracer.end_span(span)

    assert span.latency == 2.5          # 来自单调 clock，与墙钟无关
    assert span.start == 10.0           # 仍是 clock 读数，不是墙钟
    assert span.started_at.startswith("2026-08-03")


def test_default_wall_clock_is_timezone_aware():
    """缺省墙钟必须带时区——裸 datetime.now() 的串跨机器读时无从判断基准。"""
    tracer = Tracer(InMemoryExporter(), clock=_fake_clock([0.0, 1.0]), id_factory=_counter_ids())

    span = tracer.start_span("step")

    assert span.started_at is not None
    # ISO 串尾部带偏移（+00:00）或 Z；fromisoformat 解出的对象必须有 tzinfo。
    from datetime import datetime

    assert datetime.fromisoformat(span.started_at).tzinfo is not None


def test_noop_tracer_unaffected_by_wall_clock_field():
    """NoopTracer 复用父类 start_span，新字段不得让它报错、也不得产生导出。"""
    tracer = NoopTracer()
    span = tracer.start_span("step")
    tracer.end_span(span)

    assert span.started_at is not None  # 构造照常（它不导出，故无副作用）
    assert span.events == []


# ── add_observation 的 error_kind 窄提取 ────────────────────────────────────
def test_observation_lifts_error_kind_from_dict():
    """service 级失败标记要在 str() 化之前提取——之后就只剩 str(dict) 的排版，那不是契约。"""
    tracer = Tracer(InMemoryExporter(), clock=_fake_clock([0.0, 1.0]), id_factory=_counter_ids())
    span = tracer.start_span("step")

    tracer.add_observation(span, "vlog_query", {"error": "查询超时", "error_kind": "timeout"})

    obs = [e for e in span.events if e.kind == "observation"][0]
    assert obs.payload["error_kind"] == "timeout"
    assert "查询超时" in obs.payload["result"]  # 字符串化的结果照常保留


def test_observation_lifts_error_kind_from_object_attribute():
    """结果是对象（如 pydantic 模型）时走属性读取。"""
    class _Result:
        error_kind = "connect_failed"

    tracer = Tracer(InMemoryExporter(), clock=_fake_clock([0.0, 1.0]), id_factory=_counter_ids())
    span = tracer.start_span("step")

    tracer.add_observation(span, "vlog_query", _Result())

    obs = [e for e in span.events if e.kind == "observation"][0]
    assert obs.payload["error_kind"] == "connect_failed"


def test_observation_omits_error_kind_when_absent_or_empty():
    """未失败 / 空串 / 非字符串 → 不写这个键，免得下游把「有键」当成「有错」。"""
    tracer = Tracer(InMemoryExporter(), clock=_fake_clock([0.0, 1.0]), id_factory=_counter_ids())
    span = tracer.start_span("step")

    tracer.add_observation(span, "t", {"ok": True})                    # 无该键
    tracer.add_observation(span, "t", {"error_kind": None})            # 显式 None
    tracer.add_observation(span, "t", {"error_kind": ""})              # 空串
    tracer.add_observation(span, "t", {"error_kind": 500})             # 非字符串
    tracer.add_observation(span, "t", "纯字符串结果")                    # 无属性可读

    for obs in [e for e in span.events if e.kind == "observation"]:
        assert "error_kind" not in obs.payload


def test_observation_extraction_never_raises_on_hostile_result():
    """提取逻辑自身绝不抛——埋点炸掉不能把用户的正常请求带崩。"""
    class _Hostile:
        def __getattr__(self, name):
            raise RuntimeError("属性读取炸了")

        def __str__(self) -> str:
            return "<hostile>"

    tracer = Tracer(InMemoryExporter(), clock=_fake_clock([0.0, 1.0]), id_factory=_counter_ids())
    span = tracer.start_span("step")

    tracer.add_observation(span, "t", _Hostile())  # 不抛即算过

    obs = [e for e in span.events if e.kind == "observation"][0]
    assert "error_kind" not in obs.payload
