"""生产 trace 接线烟测（改造 7 · 在线评估闭环）。

验证：① 生产模块级单例已接 tracer（主 loop 与采样 exporter 串好）；② 接入 tracer 后
``ProcessUserInput_stream`` 的流式 ``[REPLY]`` 语义不变，且真实跑一次会落出可逐行解析的
trace（root span 带 user_input/session_id）。全程用离线 fake LLM，不触网。
"""

import json
from typing import Any, List, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import api.chat_handler as ch
from harness.memory.long_term import LongTermMemory
from harness.observability.file_exporter import FileSpanExporter
from harness.observability.sampling_exporter import SamplingSpanExporter
from harness.observability.tracer import Tracer
from harness.runtime import AgentLoop
from harness.runtime.session import SessionStore
from harness.tools.registry import ToolRegistry


class _CapturingModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "capturing"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_CapturingModel":
        return self

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="好的。"))])


class _NoopSummary:
    def get_read_context(self, session_id: str):
        raise NotImplementedError("offline: force short-term fallback")

    def get_summary_hint(self, session_id: str) -> str:
        return ""

    async def compact_if_needed(self, session_id: str) -> None:
        return None


def test_production_singletons_are_tracer_wired():
    # 主 loop 注入的 tracer 即模块级 _tracer，其 exporter 为采样 exporter（错误优先留存）。
    assert ch._agent_loop._tracer is ch._tracer
    assert isinstance(ch._trace_exporter, SamplingSpanExporter)
    assert ch._tracer._exporter is ch._trace_exporter


@pytest.mark.asyncio
async def test_tracing_does_not_change_streaming_and_writes_trace(tmp_path, monkeypatch):
    trace_file = tmp_path / "trace-test.jsonl"
    tracer = Tracer(SamplingSpanExporter(FileSpanExporter(path=trace_file)))
    loop = AgentLoop(llm=_CapturingModel(), registry=ToolRegistry(), tracer=tracer)

    monkeypatch.setattr(ch, "_agent_loop", loop)
    monkeypatch.setattr(ch, "_session_store", SessionStore(repo=None))
    monkeypatch.setattr(ch, "_long_term", LongTermMemory(None))
    monkeypatch.setattr(ch, "_summary", _NoopSummary())

    out = "".join([tok async for tok in ch.ProcessUserInput_stream("你好", session_id="s1")])

    # 流式语义不变：仍是 [REPLY] 前缀的最终回复。
    assert out == "[REPLY]好的。"

    # 真实落出 trace：每行可 json.loads，root span 带 user_input/session_id。
    lines = trace_file.read_text(encoding="utf-8").splitlines()
    assert lines, "应至少落出一个 span"
    recs = [json.loads(l) for l in lines]
    roots = [r for r in recs if r["parent_id"] is None]
    assert roots, "应有 root span"
    assert roots[0]["attributes"].get("user_input") == "你好"
    assert roots[0]["attributes"].get("session_id") == "s1"


# ── user_id 落进 trace（change: fix-trace-triage-blindspots）────────────────
@pytest.mark.asyncio
async def test_user_id_lands_in_root_span_attributes():
    """群聊里 34 人共享同一会话：session_id 分不出人，故 root span 另记 user_id。"""
    from harness.observability.exporter import InMemoryExporter

    exporter = InMemoryExporter()
    tracer = Tracer(exporter)
    loop = AgentLoop(llm=_CapturingModel(), registry=ToolRegistry(), tracer=tracer)

    async for _ in loop.run("你好", session_id="s1", user_id="ou_alice"):
        pass
    async for _ in loop.run("你好", session_id="s1", user_id="ou_bob"):
        pass

    roots = [s for s in exporter.spans if s.parent_id is None]
    assert [s.attributes.get("user_id") for s in roots] == ["ou_alice", "ou_bob"]
    # 同一会话：session_id 相同、user_id 不同——这正是它存在的理由。
    assert {s.attributes.get("session_id") for s in roots} == {"s1"}


@pytest.mark.asyncio
async def test_user_id_absent_keeps_previous_behaviour():
    """不传时 span 不含该属性，行为与接入前完全一致（向后兼容）。"""
    from harness.observability.exporter import InMemoryExporter

    exporter = InMemoryExporter()
    loop = AgentLoop(llm=_CapturingModel(), registry=ToolRegistry(), tracer=Tracer(exporter))

    async for _ in loop.run("你好", session_id="s1"):
        pass

    roots = [s for s in exporter.spans if s.parent_id is None]
    assert "user_id" not in roots[0].attributes


@pytest.mark.asyncio
async def test_production_handler_passes_user_id_into_trace(tmp_path, monkeypatch):
    """生产入口把提交者身份接进 trace——第 1 期传的 open_id 此前只进了 DB、没进 trace。"""
    trace_file = tmp_path / "trace-uid.jsonl"
    tracer = Tracer(SamplingSpanExporter(FileSpanExporter(path=trace_file)))
    loop = AgentLoop(llm=_CapturingModel(), registry=ToolRegistry(), tracer=tracer)

    monkeypatch.setattr(ch, "_agent_loop", loop)
    monkeypatch.setattr(ch, "_session_store", SessionStore(repo=None))
    monkeypatch.setattr(ch, "_long_term", LongTermMemory(None))
    monkeypatch.setattr(ch, "_summary", _NoopSummary())

    async for _ in ch.ProcessUserInput_stream("你好", session_id="s1", user_id="ou_carol"):
        pass

    recs = [json.loads(l) for l in trace_file.read_text(encoding="utf-8").splitlines()]
    roots = [r for r in recs if r["parent_id"] is None]
    assert roots[0]["attributes"].get("user_id") == "ou_carol"
    # 落盘记录同时带绝对时间戳（triage 按日期切窗靠它）。
    assert roots[0].get("started_at")


def test_reinjected_cases_never_carry_user_id(tmp_path):
    """★ 隐私边界：回灌产物 MUST NOT 带提交者标识——cases.jsonl 进版本库、trace 目录不进。

    `triage.CANONICAL_KEYS` 今天碰巧不含 user_id；这条测试把「碰巧」变成契约，
    使它不因后续扩字段而意外放行个人标识。
    """
    from evals.triage import CANONICAL_KEYS, append_cases

    assert "user_id" not in CANONICAL_KEYS

    cases = tmp_path / "cases.jsonl"
    cases.write_text('{"input": "已有", "expected_intent": "other"}\n', encoding="utf-8")

    append_cases(cases, [{
        "input": "值守问题",
        "expected_intent": "other",
        "user_id": "ou_carol",          # 即便草稿里混进了它
        "_trace_id": "t1",
    }])

    written = cases.read_text(encoding="utf-8")
    assert "ou_carol" not in written, "提交者标识绝不能进版本库里的用例集"
    assert "user_id" not in json.loads(written.splitlines()[-1])
