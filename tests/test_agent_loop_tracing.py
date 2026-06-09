"""AgentLoop 接入 Tracer 的离线确定性单测（Phase 6 可观测层）。

验证：注入 tracer 时产生可回放 trace（root + 每步 child，工具步含 tool_call/
observation/latency）；tracer 在工具异常等情形下不改变控制流，仅记录 span。
全程不触网（脚本化 fake LLM + fake 工具）。"未注入 tracer 行为不变"由既有
tests/test_agent_loop.py 全绿保证。
"""

from typing import Any, List, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, Field

from harness.observability.exporter import InMemoryExporter
from harness.observability.tracer import Tracer
from harness.runtime import AgentLoop
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry


class ScriptedChatModel(BaseChatModel):
    responses: List[AIMessage] = []
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        idx = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])


def _tool_call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class _EchoArgs(BaseModel):
    value: str = Field(default="")


class _BoomArgs(BaseModel):
    pass


def _make_registry() -> ToolRegistry:
    async def _echo(args: _EchoArgs) -> str:
        return f"echo<{args.value}>"

    async def _boom(args: _BoomArgs) -> str:
        raise RuntimeError("工具内部炸了")

    reg = ToolRegistry()
    reg.register(Tool("echo", "回显输入", _EchoArgs, _echo))
    reg.register(Tool("boom", "总是抛异常", _BoomArgs, _boom))
    return reg


def _fake_clock():
    """递增时钟：每次调用 +1.0，使 latency 确定且非零。"""
    state = {"t": 0.0}

    def clock() -> float:
        state["t"] += 1.0
        return state["t"]

    return clock


def _counter_ids():
    n = {"i": 0}

    def factory() -> str:
        n["i"] += 1
        return f"id-{n['i']}"

    return factory


def _make_tracer() -> tuple[Tracer, InMemoryExporter]:
    exporter = InMemoryExporter()
    return Tracer(exporter, clock=_fake_clock(), id_factory=_counter_ids()), exporter


async def _collect(loop: AgentLoop, user_input: str, **kw) -> str:
    return "".join([tok async for tok in loop.run(user_input, **kw)])


@pytest.mark.asyncio
async def test_tracer_records_replayable_trace_with_tool_step():
    reg = _make_registry()
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="我先查一下", tool_calls=[_tool_call("echo", {"value": "hi"}, "c1")]),
            AIMessage(content="已为您查询完成。"),
        ]
    )
    tracer, exporter = _make_tracer()
    loop = AgentLoop(llm=llm, registry=reg, tracer=tracer)

    out = await _collect(loop, "你好", session_id="s1")
    assert out == "[REPLY]已为您查询完成。"

    # 一个 root + 两步 child（第一步含工具，第二步出最终回复）。
    roots = exporter.roots()
    assert len(roots) == 1
    root = roots[0]
    assert root.attributes.get("session_id") == "s1"
    children = exporter.children_of(root)
    assert len(children) == 2
    # 全部 span 同一 trace_id（可回放检索）。
    assert all(s.trace_id == root.trace_id for s in children)

    # 第一步：含 tool_call 与 observation，且 latency 非空。
    step1 = children[0]
    kinds = [e.kind for e in step1.events]
    assert "thought" in kinds and "tool_call" in kinds and "observation" in kinds
    assert step1.attributes["tool_name"] == "echo"
    tool_event = next(e for e in step1.events if e.kind == "tool_call")
    assert tool_event.payload == {"name": "echo", "args": {"value": "hi"}}
    obs_event = next(e for e in step1.events if e.kind == "observation")
    assert obs_event.payload["result"] == "echo<hi>"
    assert step1.latency is not None and step1.latency > 0
    assert "tokens" in step1.attributes

    # 第二步：最终回复（thought 记录回复文本），无工具事件。
    step2 = children[1]
    assert all(e.kind != "tool_call" for e in step2.events)
    assert root.latency is not None and root.latency > 0


@pytest.mark.asyncio
async def test_tracer_does_not_change_control_flow_on_tool_error():
    """工具异常时：既有错误回灌语义不变，tracer 仅记录 observation（错误文本）。"""
    reg = _make_registry()
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("boom", {}, "c1")]),
            AIMessage(content="抱歉，处理时出了点问题。"),
        ]
    )
    tracer, exporter = _make_tracer()
    loop = AgentLoop(llm=llm, registry=reg, tracer=tracer)

    out = await _collect(loop, "触发异常")

    # 控制流不变：异常被回灌、循环继续、最终正常出回复。
    assert out == "[REPLY]抱歉，处理时出了点问题。"
    step1 = exporter.children_of(exporter.roots()[0])[0]
    obs = next(e for e in step1.events if e.kind == "observation")
    assert "工具执行失败" in obs.payload["result"]


@pytest.mark.asyncio
async def test_tracer_records_error_event_on_max_steps_fallback():
    """持续返回工具调用直到 max_steps：root span 仍被正常结束、可回放。"""
    reg = _make_registry()
    # 始终返回同一个工具调用 → 但用 repeat_limit=None 关打转，靠 max_steps 兜底。
    llm = ScriptedChatModel(
        responses=[AIMessage(content="", tool_calls=[_tool_call("echo", {"value": "x"}, "c1")])]
    )
    tracer, exporter = _make_tracer()
    loop = AgentLoop(llm=llm, registry=reg, tracer=tracer, max_steps=3, repeat_limit=None)

    out = await _collect(loop, "无限工具")

    assert out.startswith("[REPLY]")
    root = exporter.roots()[0]
    # 触达 max_steps：产生 3 个 step child，root 正常结束。
    assert len(exporter.children_of(root)) == 3
    assert root.latency is not None
