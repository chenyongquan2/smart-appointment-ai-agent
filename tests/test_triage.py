"""triage + 采样 exporter 的离线确定性单测（改造 7 · 在线评估闭环）。

覆盖：① detect_bad_signals 各信号口径；② SamplingSpanExporter 错误优先留存；
③ triage_traces 按 trace_id 分组甄别 + 还原 input；④ append_cases 去重/溯源/不改基线。
全程不触网、不调 LLM。
"""

import json

import pytest

from harness.observability.file_exporter import FileSpanExporter
from harness.observability.sampling_exporter import SamplingSpanExporter
from harness.observability.span import Span, SpanEvent
from harness.observability.trace_signals import detect_bad_signals, is_bad_trace

from evals.triage import (
    append_cases,
    filter_traces_since,
    load_existing_inputs,
    load_trace_spans,
    normalize_input,
    parse_since,
    signal_counts,
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


# ── 工具超时信号（change: fix-trace-triage-blindspots）──────────────────────
# 修前这一组全部返回 []：超时支从 except Exception 拆出去时，"工具执行超时"不匹配
# "工具执行失败"前缀，于是超时静默不再命中。文案与判定现同源于 harness/tool_outcome.py，
# 端到端的防漂移守卫在 tests/test_tool_outcome.py。
def _obs_kind(name, result, error_kind):
    """带结构化 error_kind 的 observation（Tracer.add_observation 在 str() 化前提取的那个键）。"""
    return SpanEvent("observation", {"name": name, "result": result, "error_kind": error_kind})


def test_signal_loop_level_tool_timeout():
    """loop 级：_dispatch 的 wait_for 掐断，按文案前缀认。"""
    spans = [_root("t", 0), _step("t", "s1", 1, [_tc("vlog_query"),
             _obs("vlog_query", "工具执行超时（vlog_query）：超过 60 秒未返回，已中断且不会重试。")])]
    assert "tool_timeout" in detect_bad_signals(spans)


def test_signal_service_level_structured_timeout():
    """service 级：工具**正常返回**、loop 层面无任何异常，只有结果里带 error_kind=timeout。

    这条路径今天完全不可见——`_dispatch` 没抛异常，从它看这次调用是成功的。
    """
    spans = [_root("t", 0), _step("t", "s1", 1, [_tc("vlog_query"),
             _obs_kind("vlog_query", "{'error': '查询超时', 'error_kind': 'timeout'}", "timeout")])]
    assert "tool_timeout" in detect_bad_signals(spans)


def test_signal_service_level_non_timeout_error_kind_is_failure():
    """connect_failed / http_error / other 同属真失败——它们今天同样完全不可见。"""
    for kind in ("connect_failed", "http_error", "other"):
        spans = [_root("t", 0), _step("t", "s1", 1, [_tc("vlog_query"),
                 _obs_kind("vlog_query", "{'error_kind': '%s'}" % kind, kind)])]
        signals = detect_bad_signals(spans)
        assert "tool_failure" in signals, kind
        assert "tool_timeout" not in signals, kind


def test_signal_real_group_chat_triple_timeout():
    """★ 回归本 change 存在的理由：真实群聊 2026-08-03 的那次坏 case。

    模型追 traceId 时把窗口 6h→2d→7d 越拓越宽，**连吃三次 60 秒超时、白等 3 分钟**，
    最后仍产出了终态回复（故 max_steps 也不命中）。修前 triage 对它报 0 个候选——
    最常见的真实故障恰好不可见。
    """
    timeout_obs = "工具执行超时（vlog_query）：超过 60 秒未返回，已中断且不会重试。"
    spans = [
        _root("t", 0),
        _step("t", "s1", 1, [_tc("vlog_query"), _obs("vlog_query", timeout_obs)]),
        _step("t", "s2", 2, [_tc("vlog_query"), _obs("vlog_query", timeout_obs)]),
        _step("t", "s3", 3, [_tc("vlog_query"), _obs("vlog_query", timeout_obs)]),
        _step("t", "s4", 4, [SpanEvent("thought", {"text": "查不到，建议收窄时间窗"})]),  # 终态
    ]
    signals = detect_bad_signals(spans)
    assert signals, "真实群聊的三连超时必须命中信号——修前这里是空清单"
    assert "tool_timeout" in signals
    assert "max_steps_reached" not in signals  # 它确实产出了终态回复，别归错因


def test_guide_status_returns_are_not_signals():
    """⚠ 不得泛化成「任何错误类字段」：`services/repo.py` 的 need_clone 等是**正常引导状态**。

    `GUIDE_STATUS = {ready, need_clone, branch_not_found, bad_env, need_git_url}`，且
    `LocateResult.ok` 就是 `status in GUIDE_STATUS`。把"仓库还没备好、请运维 clone"当成
    疑似坏候选会毁掉 triage 的信噪比——误报比漏报更致命。
    """
    for status in ("need_clone", "branch_not_found", "bad_env", "need_git_url"):
        spans = [
            _root("t", 0),
            _step("t", "s1", 1, [_tc("locate_service_code"),
                  _obs("locate_service_code", "{'ok': True, 'status': '%s'}" % status)]),
            _step("t", "s2", 2, [SpanEvent("thought", {"text": "已如实告知用户"})]),
        ]
        assert detect_bad_signals(spans) == [], f"{status} 是正常引导状态，不该产生信号"


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


def test_sampling_keeps_timeout_only_trace_at_rate_zero(tmp_path):
    """仅命中超时信号的 trace 也必须不受采样率影响——修前它会被当成「非错误」丢掉。

    今天 EVAL_TRACE_SAMPLE_RATE=1.0 全量留、没丢东西；一旦有人为省盘调低采样率，
    丢掉的恰好是最该留的那批。
    """
    inner = FileSpanExporter(path=tmp_path / "t.jsonl")
    exp = SamplingSpanExporter(inner, sample_rate=0.0, rng=lambda: 0.99)
    timeout_obs = "工具执行超时（vlog_query）：超过 60 秒未返回，已中断且不会重试。"
    bad = [_root("t", 0), _step("t", "s1", 1, [_tc("vlog_query"), _obs("vlog_query", timeout_obs)])]
    _emit(exp, bad)
    lines = (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, "超时 trace 必留，不受采样率影响"


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


# ── 墙钟时间戳与时间窗筛选（change: fix-trace-triage-blindspots）────────────
def _legacy_line(trace_id, span_id, parent_id, name, events=None, attributes=None):
    """手写一条**旧格式** span 记录：没有 started_at 键（本 change 之前落的 trace 就是这样）。"""
    return json.dumps({
        "event": "span", "trace_id": trace_id, "span_id": span_id, "parent_id": parent_id,
        "name": name, "latency": 0.1,
        "attributes": attributes or {}, "events": events or [],
    }, ensure_ascii=False)


def test_load_trace_spans_reads_started_at_and_tolerates_absence(tmp_path):
    """新格式带 started_at；旧格式缺键 → None，且 MUST 仍能正常加载。

    盘上已有的 trace 文件是目前唯一的真实流量原料，引入新字段绝不能让它们失效。
    """
    f = tmp_path / "t.jsonl"
    new_line = json.dumps({
        "event": "span", "trace_id": "new", "span_id": "n1", "parent_id": None,
        "name": "agent_loop.run", "latency": 0.2, "started_at": "2026-08-03T10:00:00+00:00",
        "attributes": {"user_input": "新的"}, "events": [],
    }, ensure_ascii=False)
    f.write_text(new_line + "\n" + _legacy_line("old", "o1", None, "agent_loop.run",
                 attributes={"user_input": "旧的"}) + "\n", encoding="utf-8")

    spans = {s.trace_id: s for s in load_trace_spans(f)}
    assert spans["new"].started_at == "2026-08-03T10:00:00+00:00"
    assert spans["old"].started_at is None  # 缺键不报错、不伪造时间
    assert spans["old"].attributes["user_input"] == "旧的"  # 其余字段照常可用


def test_legacy_trace_file_triage_result_unchanged(tmp_path):
    """对不含 started_at 的旧格式文件跑甄别，结果与引入新字段前一致。"""
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join([
        _legacy_line("bad", "root", None, "agent_loop.run", attributes={"user_input": "旧的坏 case"}),
        _legacy_line("bad", "b1", "root", "step", events=[
            {"kind": "tool_call", "payload": {"name": "vlog_query", "args": {}}},
            {"kind": "observation", "payload": {"name": "vlog_query",
             "result": "工具执行失败（vlog_query）：boom"}},
        ]),
    ]) + "\n", encoding="utf-8")

    cands = triage_traces(load_trace_spans(f))
    assert len(cands) == 1
    assert cands[0]["input"] == "旧的坏 case"
    assert "tool_failure" in cands[0]["_signals"]


def test_parse_since_requires_timezone():
    """裸时间串必须报错——猜时区的错会安静地把窗口整体挪几小时，比报错难查得多。"""
    assert parse_since("2026-08-03T00:00:00Z").tzinfo is not None
    assert parse_since("2026-08-03T08:00:00+08:00").tzinfo is not None
    with pytest.raises(ValueError, match="必须带时区"):
        parse_since("2026-08-03T00:00:00")


def test_filter_traces_since_keeps_whole_group():
    """按 trace 组筛而非逐 span：否则窗口边界上会丢掉 root、草稿的 input 就空了。"""
    early_root = Span("early", "early-root", None, "agent_loop.run", 0.0, 0.0,
                      started_at="2026-08-01T00:00:00+00:00", attributes={"user_input": "早的"})
    early_step = Span("early", "e1", "early-root", "step", 1.0, 1.0,
                      started_at="2026-08-01T00:00:01+00:00")
    late_root = Span("late", "late-root", None, "agent_loop.run", 2.0, 2.0,
                     started_at="2026-08-05T00:00:00+00:00", attributes={"user_input": "晚的"})
    late_step = Span("late", "l1", "late-root", "step", 3.0, 3.0,
                     started_at="2026-08-05T00:00:01+00:00")

    kept, legacy = filter_traces_since(
        [early_root, early_step, late_root, late_step], parse_since("2026-08-03T00:00:00Z")
    )

    assert {s.trace_id for s in kept} == {"late"}
    assert len(kept) == 2, "整组保留（root + step），不能只留 step"
    assert legacy == 0


def test_filter_traces_since_includes_and_counts_legacy():
    """无墙钟的历史 trace **一律纳入并计数**——绝不静默丢弃真实原料。

    静默排除会让「0 个候选」这个结论第二次骗人。
    """
    legacy_root = Span("legacy", "legacy-root", None, "agent_loop.run", 0.0, 0.0,
                       attributes={"user_input": "旧的"})  # started_at=None
    late_root = Span("late", "late-root", None, "agent_loop.run", 1.0, 1.0,
                     started_at="2026-08-05T00:00:00+00:00")

    kept, legacy = filter_traces_since([legacy_root, late_root], parse_since("2026-08-03T00:00:00Z"))

    assert {s.trace_id for s in kept} == {"legacy", "late"}
    assert legacy == 1, "被无条件纳入的历史 trace 组数要报出来"


def test_signal_counts_summarizes_by_label():
    """攒量后要的是「这周超时 12 次、打转 3 次」，不只是候选总数。"""
    counts = signal_counts([
        {"_signals": ["tool_timeout"]},
        {"_signals": ["tool_timeout", "tool_failure"]},
        {"_signals": []},
    ])
    assert counts == {"tool_failure": 1, "tool_timeout": 2}


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
