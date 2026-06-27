"""triage + 采样 exporter 的离线确定性单测（改造 7 · 在线评估闭环）。

覆盖：① detect_bad_signals 各信号口径；② SamplingSpanExporter 错误优先留存；
③ triage_traces 按 trace_id 分组甄别 + 还原 input；④ append_cases 去重/溯源/不改基线。
全程不触网、不调 LLM。
"""

import json

from harness.observability.file_exporter import FileSpanExporter
from harness.observability.sampling_exporter import SamplingSpanExporter
from harness.observability.span import Span, SpanEvent
from harness.observability.trace_signals import detect_bad_signals, is_bad_trace

from evals.triage import (
    append_cases,
    load_existing_inputs,
    load_trace_spans,
    normalize_input,
    triage_traces,
)


# ── 测试用 span 构造 ────────────────────────────────────────────────────────
def _root(trace_id, start, user_input="原话", sid="s1"):
    return Span(trace_id, f"{trace_id}-root", None, "agent_loop.run", start,
               start, attributes={"user_input": user_input, "session_id": sid})


def _step(trace_id, span_id, start, events):
    return Span(trace_id, span_id, f"{trace_id}-root", "step", start, start, events=events)


def _tc(name, args=None):
    return SpanEvent("tool_call", {"name": name, "args": args or {}})


def _obs(name, result):
    return SpanEvent("observation", {"name": name, "result": result})


def _err(kind):
    return SpanEvent("error", {"type": kind})


# ── detect_bad_signals ───────────────────────────────────────────────────────
def test_signal_clean_trace_has_no_signals():
    spans = [_root("t", 0), _step("t", "s1", 1, [_tc("find_technician"), _obs("find_technician", "ok")]),
             _step("t", "s2", 2, [SpanEvent("thought", {"text": "已完成"})])]  # 终态：无 tool_call
    assert detect_bad_signals(spans) == []
    assert is_bad_trace(spans) is False


def test_signal_tool_failure():
    spans = [_root("t", 0), _step("t", "s1", 1, [_tc("create_appointment"),
             _obs("create_appointment", "工具执行失败（create_appointment）：boom")])]
    assert "tool_failure" in detect_bad_signals(spans)


def test_signal_guardrail_and_spin_from_error_events():
    g = [_root("t", 0), _step("t", "s1", 1, [_err("guardrail_exhausted")])]
    assert detect_bad_signals(g) == ["guardrail_exhausted"]
    sp = [_root("u", 0), _step("u", "s1", 1, [_err("spin_detected")])]
    assert detect_bad_signals(sp) == ["spin_detected"]


def test_signal_max_steps_when_last_step_still_calls_tool():
    # 无 error，但最后一步仍在调工具（未产终态回复）→ 跑满步数/预算耗尽。
    spans = [_root("t", 0),
             _step("t", "s1", 1, [_tc("find_technician"), _obs("find_technician", "ok")]),
             _step("t", "s2", 2, [_tc("check_availability"), _obs("check_availability", "ok")])]
    assert detect_bad_signals(spans) == ["max_steps_reached"]


# ── SamplingSpanExporter ─────────────────────────────────────────────────────
def _emit(exporter, spans):
    # 模拟到达顺序：child 先于 root（AgentLoop 在最外层 finally 关 root）。
    for s in spans:
        if s.parent_id is not None:
            exporter.export(s)
    for s in spans:
        if s.parent_id is None:
            exporter.export(s)


def test_sampling_keeps_error_trace_even_at_rate_zero(tmp_path):
    inner = FileSpanExporter(path=tmp_path / "t.jsonl")
    exp = SamplingSpanExporter(inner, sample_rate=0.0, rng=lambda: 0.99)  # 非错误必被丢
    bad = [_root("t", 0), _step("t", "s1", 1, [_err("spin_detected")])]
    _emit(exp, bad)
    lines = (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # 错误 trace 不受采样率影响，整组留存


def test_sampling_drops_clean_trace_at_rate_zero(tmp_path):
    inner = FileSpanExporter(path=tmp_path / "t.jsonl")
    exp = SamplingSpanExporter(inner, sample_rate=0.0, rng=lambda: 0.99)
    clean = [_root("t", 0), _step("t", "s1", 1, [SpanEvent("thought", {"text": "好"})])]
    _emit(exp, clean)
    assert not (tmp_path / "t.jsonl").exists() or (tmp_path / "t.jsonl").read_text() == ""


def test_sampling_keeps_all_at_default_rate(tmp_path):
    inner = FileSpanExporter(path=tmp_path / "t.jsonl")
    exp = SamplingSpanExporter(inner, sample_rate=1.0, rng=lambda: 0.99)
    clean = [_root("t", 0), _step("t", "s1", 1, [SpanEvent("thought", {"text": "好"})])]
    _emit(exp, clean)
    assert len((tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()) == 2


# ── triage_traces（含文件往返） ──────────────────────────────────────────────
def test_triage_groups_by_trace_and_recovers_input(tmp_path):
    inner = FileSpanExporter(path=tmp_path / "t.jsonl")
    # 一条坏 trace（工具失败）+ 一条干净 trace。
    _emit(inner, [_root("bad", 0, user_input="约不到张三怎么办"),
                  _step("bad", "b1", 1, [_tc("find_technician"), _obs("find_technician", "工具执行失败（find_technician）：x")])])
    _emit(inner, [_root("ok", 10, user_input="你们几点开门"),
                  _step("ok", "o1", 11, [SpanEvent("thought", {"text": "九点"})])])

    spans = load_trace_spans(tmp_path / "t.jsonl")
    cands = triage_traces(spans)
    assert len(cands) == 1  # 只有坏 trace 入选
    c = cands[0]
    assert c["input"] == "约不到张三怎么办"
    assert "tool_failure" in c["_signals"]
    assert c["expected_intent"] == ""  # 真值留空待人填
    assert c["source"] == "online"
    assert "find_technician" in c["_observed_tools"]


# ── append_cases 去重/溯源/不改基线 ──────────────────────────────────────────
def _seed_cases(path):
    path.write_text(
        '// 评估用例\n{"input": "你们有哪些项目", "expected_intent": "query", "expected_tools": ["search_knowledge"]}\n',
        encoding="utf-8",
    )


def test_append_adds_new_with_source_tag(tmp_path):
    cases = tmp_path / "cases.jsonl"
    _seed_cases(cases)
    report = append_cases(cases, [{"input": "约不到张三", "expected_intent": "appointment",
                                   "expected_tools": ["find_technician"]}])
    assert len(report["added"]) == 1
    # 可被 load_existing_inputs 读到，且带 source=online。
    text = cases.read_text(encoding="utf-8")
    assert "online 回灌" in text
    last = json.loads(text.splitlines()[-1])
    assert last["source"] == "online"
    assert last["input"] == "约不到张三"


def test_append_skips_existing_and_batch_dups(tmp_path):
    cases = tmp_path / "cases.jsonl"
    _seed_cases(cases)
    report = append_cases(cases, [
        {"input": "你们有哪些项目", "expected_intent": "query"},   # 与现有等价
        {"input": "新问题A", "expected_intent": "other"},
        {"input": "新问题A", "expected_intent": "other"},          # 批内重复
    ])
    assert len(report["added"]) == 1
    reasons = [r for _, r in report["skipped"]]
    assert "exists" in reasons and "dup-in-batch" in reasons


def test_append_drops_helper_fields_and_does_not_touch_baseline(tmp_path):
    cases = tmp_path / "cases.jsonl"
    _seed_cases(cases)
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"version": 1}', encoding="utf-8")

    append_cases(cases, [{"input": "带辅助字段", "expected_intent": "other",
                          "_trace_id": "x", "_signals": ["spin_detected"]}])
    last = json.loads(cases.read_text(encoding="utf-8").splitlines()[-1])
    assert "_trace_id" not in last and "_signals" not in last  # 辅助字段不写进用例集
    # 回灌绝不动基线文件。
    assert baseline.read_text(encoding="utf-8") == '{"version": 1}'


def test_normalize_input_collapses_whitespace_and_case():
    assert normalize_input("  Hello   World ") == "hello world"
