"""子 Agent tracer 透传单测（change: evals-drive-agentloop-real-tools）。

验证 observability spec 新增要求：注入主 Agent 的 tracer 能透传进子 Agent 的内层
``AgentLoop``，使子 Agent 步内的 tool_call / observation 被导出（消除盲区）；未注入时
（缺省 NoopTracer）子 Agent 不产生任何 span 导出，行为与透传前完全一致。

全程用脚本化 fake LLM 驱动，离线、不触网、不触碰 services/。
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
from harness.subagents import SubAgent, build_delegate_tool
from harness.subagents.registry import SubAgentRegistry
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry


# --------------------------------------------------------------------------- #
# 脚本化 fake LLM（与 test_subagents 一致）。
# --------------------------------------------------------------------------- #
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


class _Args(BaseModel):
    value: str = Field(default="")


def _registry_with_echo() -> ToolRegistry:
    async def _echo(args: _Args) -> str:
        return f"echo<{args.value}>"

    reg = ToolRegistry()
    reg.register(Tool("echo", "回显", _Args, _echo))
    return reg


def _echoer_subagents() -> SubAgentRegistry:
    reg = SubAgentRegistry()
    reg.register(
        SubAgent(
            name="echoer",
            description="只会回显",
            tool_names=("echo",),
            system_prompt="你只会用 echo。",
        )
    )
    return reg


def _tool_call_events(spans) -> list[dict]:
    """从一组 span 收集所有 tool_call 事件的 payload（按 span 导出顺序）。"""
    out: list[dict] = []
    for s in spans:
        for e in s.events:
            if e.kind == "tool_call":
                out.append(e.payload)
    return out


# --------------------------------------------------------------------------- #
# 1.3 注入真 tracer：子 Agent 步内工具调用可被导出
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_subagent_tool_call_exported_when_tracer_injected():
    full = _registry_with_echo()
    subagents = _echoer_subagents()
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("echo", {"value": "x"}, "c1")]),
            AIMessage(content="子任务完成。"),
        ]
    )
    exporter = InMemoryExporter()
    tracer = Tracer(exporter)
    delegate = build_delegate_tool(llm, full, subagents, tracer=tracer)

    out = await delegate.run({"subagent": "echoer", "task": "回显 x"})

    assert out == {"success": True, "subagent": "echoer", "result": "子任务完成。"}
    # 关键断言：子 Agent 内层的 echo 工具调用被导出，而非不可见。
    calls = _tool_call_events(exporter.spans)
    assert any(c["name"] == "echo" and c["args"] == {"value": "x"} for c in calls)
    # observation 同样被记录。
    observations = [
        e.payload for s in exporter.spans for e in s.events if e.kind == "observation"
    ]
    assert any(o["name"] == "echo" for o in observations)


# --------------------------------------------------------------------------- #
# 1.4 未注入 tracer：无 span 导出、行为与透传前一致（向后兼容）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_subagent_no_span_exported_without_tracer():
    full = _registry_with_echo()
    subagents = _echoer_subagents()
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("echo", {"value": "x"}, "c1")]),
            AIMessage(content="子任务完成。"),
        ]
    )
    exporter = InMemoryExporter()
    # 不传 tracer：子 Agent 内层 loop 退化 NoopTracer，不应往 exporter 导出任何 span。
    delegate = build_delegate_tool(llm, full, subagents)

    out = await delegate.run({"subagent": "echoer", "task": "回显 x"})

    assert out == {"success": True, "subagent": "echoer", "result": "子任务完成。"}
    assert exporter.spans == []  # 行为与透传前完全一致：零导出


@pytest.mark.asyncio
async def test_subagent_run_tracer_default_none_unchanged():
    """SubAgent.run 不传 tracer 时正常返回最终文本（缺省参数向后兼容）。"""
    full = _registry_with_echo()
    agent = SubAgent(
        name="echoer", description="只会回显", tool_names=("echo",), system_prompt="x"
    )
    llm = ScriptedChatModel(responses=[AIMessage(content="完成。")])

    result = await agent.run("回显", full, llm)

    assert result == "完成。"
