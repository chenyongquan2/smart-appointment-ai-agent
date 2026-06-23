"""evals/agent_capture.capture_tool_calls 的离线确定性单测。

用脚本化 fake LLM 驱动「主 Agent → delegate → 子 Agent → 领域工具」的真实路径，
断言 capture_tool_calls 采到子 Agent 内实际触发的工具（而非只有 delegate），且
tool_call_correctness 据此从 N/A 翻成真实数字。全程离线、不触网、不触碰 services/。
"""

from typing import Any, List, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, Field

from evals.agent_capture import capture_tool_calls
from evals.metrics import EvalResult, tool_call_correctness
from harness.subagents import SubAgent
from harness.subagents.registry import SubAgentRegistry
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


class _Args(BaseModel):
    value: str = Field(default="")


def _fixtures() -> tuple[ToolRegistry, SubAgentRegistry]:
    async def _echo(args: _Args) -> str:
        return f"echo<{args.value}>"

    full = ToolRegistry()
    full.register(Tool("echo", "回显", _Args, _echo))
    subagents = SubAgentRegistry()
    subagents.register(
        SubAgent(
            name="echoer",
            description="只会回显",
            tool_names=("echo",),
            system_prompt="你只会用 echo。",
        )
    )
    return full, subagents


@pytest.mark.asyncio
async def test_capture_collects_subagent_domain_tool_not_delegate():
    full, subagents = _fixtures()
    # 主 step1：派生 echoer → 子 step1：调 echo → 子 step2：回复 → 主 step2：终复。
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[
                _tool_call("delegate", {"subagent": "echoer", "task": "回显 x"}, "c1")
            ]),
            AIMessage(content="", tool_calls=[_tool_call("echo", {"value": "x"}, "c2")]),
            AIMessage(content="子任务完成。"),
            AIMessage(content="已完成。"),
        ]
    )

    actual_tools = await capture_tool_calls("回显 x", llm, full, subagents)

    # 采到的是子 Agent 内的领域工具 echo（含 args），delegate 被默认剔除。
    assert actual_tools == [{"name": "echo", "args": {"value": "x"}}]


@pytest.mark.asyncio
async def test_tool_call_correctness_flips_from_na_to_real_after_capture():
    full, subagents = _fixtures()
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[
                _tool_call("delegate", {"subagent": "echoer", "task": "回显 x"}, "c1")
            ]),
            AIMessage(content="", tool_calls=[_tool_call("echo", {"value": "x"}, "c2")]),
            AIMessage(content="子任务完成。"),
            AIMessage(content="已完成。"),
        ]
    )

    # 未真跑（actual_tools=None）→ 指标 N/A，不伪造分母。
    na = tool_call_correctness([EvalResult("回显 x", "query", expected_tools=["echo"])])
    assert na.na and na.value is None

    # 真跑采集后填入 actual_tools → 指标翻成真实数字（echo 命中 → 1/1）。
    actual_tools = await capture_tool_calls("回显 x", llm, full, subagents)
    real = tool_call_correctness([
        EvalResult("回显 x", "query", expected_tools=["echo"], actual_tools=actual_tools)
    ])
    assert not real.na
    assert (real.numerator, real.denominator) == (1, 1)
    assert real.value == 1.0
