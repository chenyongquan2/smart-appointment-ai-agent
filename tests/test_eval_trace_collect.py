"""evals/trace_collect.collect_tool_calls 的离线确定性单测。

构造「跨多棵子 Agent trace 树」的合成 span（C-lite 下子 Agent 各自开 root），
验证还原出的有序工具序列正确、按 (span.start, 事件顺序) 排列、默认剔除 delegate、
并保留每次调用的 args（采全）。纯数据断言，不触网、不跑 LLM。
"""

from harness.observability.span import Span, SpanEvent
from evals.trace_collect import collect_tool_calls


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
