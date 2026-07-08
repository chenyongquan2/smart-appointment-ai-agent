"""evals/trace_collect.collect_tool_calls 的离线确定性单测。

构造「跨多棵子 Agent trace 树」的合成 span（C-lite 下子 Agent 各自开 root），
验证还原出的有序工具序列正确、按 (span.start, 事件顺序) 排列、默认剔除 delegate、
并保留每次调用的 args（采全）。纯数据断言，不触网、不跑 LLM。
"""

from harness.observability.span import Span, SpanEvent
from evals.trace_collect import collect_tool_calls, collect_tool_outcomes


def _span(trace_id, span_id, start, *tool_calls, parent_id=None):
    """造一个带若干 tool_call 事件的 span。tool_calls 为 (name, args) 元组。"""
    events = [
        SpanEvent(kind="tool_call", payload={"name": n, "args": a}) for n, a in tool_calls
    ]
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_id=parent_id,
        name="step",
        start=start,
        end=start + 1,
        events=events,
    )


def test_collect_across_multiple_subagent_trace_trees_in_order():
    # 主 trace（traceA）step：delegate（编排，应被剔除），start=1。
    main_step = _span("traceA", "s1", 1.0, ("delegate", {"subagent": "appointment"}))
    # 子 Agent A 自开的 root/step（traceB，独立 trace_id），start=2：find_technician。
    sub1 = _span("traceB", "s2", 2.0, ("find_technician", {"project": "肩颈"}))
    # 子 Agent A 第二步（traceB），start=3：create_appointment。
    sub2 = _span("traceB", "s3", 3.0, ("create_appointment", {"time": "14:00"}))
    # 故意打乱传入顺序，验证函数自己按 start 排序。
    result = collect_tool_calls([sub2, main_step, sub1])

    # delegate 被剔除；其余按 start 升序：find_technician → create_appointment。
    assert [t["name"] for t in result] == ["find_technician", "create_appointment"]
    # 采全：args 被保留。
    assert result[0]["args"] == {"project": "肩颈"}
    assert result[1]["args"] == {"time": "14:00"}


def test_collect_orders_events_within_same_span():
    # 同一 span 内多个 tool_call：保留事件追加顺序。
    span = _span("t", "s1", 1.0, ("a", {}), ("b", {}), ("c", {}))
    assert [t["name"] for t in collect_tool_calls([span])] == ["a", "b", "c"]


def test_collect_excludes_delegate_by_default_but_keeps_domain_tools():
    span = _span("t", "s1", 1.0, ("delegate", {}), ("search_knowledge", {"q": "x"}))
    result = collect_tool_calls([span])
    assert [t["name"] for t in result] == ["search_knowledge"]


def test_collect_custom_exclude():
    span = _span("t", "s1", 1.0, ("delegate", {}), ("echo", {}))
    # 自定义 exclude=空集 → 不剔除任何工具（delegate 也保留）。
    result = collect_tool_calls([span], exclude=set())
    assert [t["name"] for t in result] == ["delegate", "echo"]


def test_collect_ignores_non_tool_call_events():
    span = Span(
        trace_id="t", span_id="s1", parent_id=None, name="step", start=1.0, end=2.0,
        events=[
            SpanEvent(kind="thought", payload={"text": "想一下"}),
            SpanEvent(kind="tool_call", payload={"name": "echo", "args": {}}),
            SpanEvent(kind="observation", payload={"name": "echo", "result": "ok"}),
        ],
    )
    assert [t["name"] for t in collect_tool_calls([span])] == ["echo"]


def test_collect_empty():
    assert collect_tool_calls([]) == []


# ── collect_tool_outcomes：工具执行成败（change evals-task-success-rate）──────

def _obs_span(trace_id, span_id, start, *observations, parent_id=None):
    """造一个带若干 observation 事件的 span。observations 为 (name, result) 元组。"""
    events = [
        SpanEvent(kind="observation", payload={"name": n, "result": r})
        for n, r in observations
    ]
    return Span(
        trace_id=trace_id, span_id=span_id, parent_id=parent_id, name="step",
        start=start, end=start + 1, events=events,
    )


def test_outcomes_success_and_failure():
    # 成功 observation → ok=True；「工具执行失败…」→ ok=False。
    span = _obs_span(
        "t", "s1", 1.0,
        ("find_technician", "找到技师李师傅"),
        ("create_appointment", "工具执行失败（DBError）：连接超时"),
    )
    result = collect_tool_outcomes([span])
    assert result == [
        {"name": "find_technician", "ok": True},
        {"name": "create_appointment", "ok": False},
    ]


def test_outcomes_order_across_spans_by_start():
    # 跨 span 按 start 排序（子 Agent 各自 span）；故意打乱传入顺序。
    s_late = _obs_span("tB", "s3", 3.0, ("create_appointment", "预约已创建"))
    s_early = _obs_span("tB", "s2", 2.0, ("find_technician", "ok"))
    result = collect_tool_outcomes([s_late, s_early])
    assert [o["name"] for o in result] == ["find_technician", "create_appointment"]
    assert all(o["ok"] for o in result)


def test_outcomes_excludes_delegate_by_default():
    span = _obs_span("t", "s1", 1.0, ("delegate", "已派给 appointment"), ("search_knowledge", "命中3条"))
    result = collect_tool_outcomes([span])
    assert result == [{"name": "search_knowledge", "ok": True}]


def test_outcomes_ignores_non_observation_events():
    span = Span(
        trace_id="t", span_id="s1", parent_id=None, name="step", start=1.0, end=2.0,
        events=[
            SpanEvent(kind="tool_call", payload={"name": "create_appointment", "args": {}}),
            SpanEvent(kind="thought", payload={"text": "下单"}),
            SpanEvent(kind="observation", payload={"name": "create_appointment", "result": "已创建"}),
        ],
    )
    # 只采 observation：终态工具成功一次。
    assert collect_tool_outcomes([span]) == [{"name": "create_appointment", "ok": True}]


def test_outcomes_empty():
    assert collect_tool_outcomes([]) == []
