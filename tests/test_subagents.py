"""SubAgent / delegate / 主 Agent 派生 端到端单测（Phase 7）。

覆盖任务 1.2（AgentLoop system_prompt 覆盖）、3.3（子 Agent 隔离与子集）、
4.4（三个专用子 Agent 工具子集）、5.2（delegate 派生）、8.2（主 Agent 经 delegate
自主派生端到端）。用脚本化 fake LLM 驱动，全程离线、不触网、不触碰 services/。
"""

from typing import Any, List, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, Field

from harness.runtime import AgentLoop
from domains import load_domain
from harness.runtime.system_prompt import (
    GENERIC_BASE_PROMPT,
    build_system_prompt,
)

_DOMAIN = load_domain()
from harness.subagents import SubAgent, build_delegate_tool
from tests._domain_helpers import build_default_subagent_registry
from domains.appointment.subagents.appointment import APPOINTMENT_SUBAGENT
from domains.appointment.subagents.consultant import CONSULTANT_SUBAGENT
from domains.appointment.subagents.user_behavior import USER_BEHAVIOR_SUBAGENT
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry
from tests._domain_helpers import build_default_registry


# --------------------------------------------------------------------------- #
# 脚本化 fake LLM（与 test_agent_loop 一致）：按序返回 AIMessage，共享调用计数。
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


def _fake_full_registry() -> tuple[ToolRegistry, list[str]]:
    log: list[str] = []

    async def _echo(args: _Args) -> str:
        log.append(f"echo:{args.value}")
        return f"echo<{args.value}>"

    async def _secret(args: _Args) -> str:
        log.append("secret")
        return "secret-result"

    reg = ToolRegistry()
    reg.register(Tool("echo", "回显", _Args, _echo))
    reg.register(Tool("secret", "不该被子 Agent 看到", _Args, _secret))
    return reg, log


# --------------------------------------------------------------------------- #
# 1.2 AgentLoop system_prompt 覆盖
# --------------------------------------------------------------------------- #
def test_agent_loop_default_system_prompt_unchanged():
    reg, _ = _fake_full_registry()
    llm = ScriptedChatModel(responses=[AIMessage(content="hi")])
    loop = AgentLoop(llm=llm, registry=reg)
    assert loop.system_prompt == build_system_prompt(GENERIC_BASE_PROMPT, reg)


def test_agent_loop_custom_system_prompt_used():
    reg, _ = _fake_full_registry()
    llm = ScriptedChatModel(responses=[AIMessage(content="hi")])
    loop = AgentLoop(llm=llm, registry=reg, system_prompt="我是专用提示。")
    assert loop.system_prompt == "我是专用提示。"


# --------------------------------------------------------------------------- #
# 3.3 子 Agent 隔离与工具子集
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_subagent_runs_in_subset_returns_final_text():
    reg, log = _fake_full_registry()
    agent = SubAgent(
        name="echoer",
        description="只会回显",
        tool_names=("echo",),
        system_prompt="你只会用 echo。",
    )
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("echo", {"value": "x"}, "c1")]),
            AIMessage(content="子任务完成。"),
        ]
    )

    result = await agent.run("回显 x", reg, llm)

    # 返回的是剥离 [REPLY] 前缀的最终文本（中间步骤不外泄）
    assert result == "子任务完成。"
    assert log == ["echo:x"]


@pytest.mark.asyncio
async def test_subagent_cannot_call_tools_outside_subset():
    """子 Agent 只持有 echo；若模型尝试调用 subset 外的 secret，会被隔离为错误回灌而非执行。"""
    reg, log = _fake_full_registry()
    agent = SubAgent(
        name="echoer",
        description="只会回显",
        tool_names=("echo",),
        system_prompt="你只会用 echo。",
    )
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("secret", {"value": "x"}, "c1")]),
            AIMessage(content="无法访问该工具。"),
        ]
    )

    result = await agent.run("尝试越权", reg, llm)

    assert result == "无法访问该工具。"
    assert "secret" not in log  # subset 外的工具绝不被执行


# --------------------------------------------------------------------------- #
# 4.4 三个专用子 Agent 的工具子集
# --------------------------------------------------------------------------- #
def test_specialized_subagents_tool_subsets():
    assert set(APPOINTMENT_SUBAGENT.tool_names) == {
        "find_technician",
        "check_availability",
        "create_appointment",
        "get_user_preferences",
    }
    assert CONSULTANT_SUBAGENT.tool_names == ("search_knowledge",)
    # 咨询子 Agent 不持有写库的 create_appointment
    assert "create_appointment" not in CONSULTANT_SUBAGENT.tool_names
    assert USER_BEHAVIOR_SUBAGENT.tool_names == ("get_user_preferences",)


def test_specialized_subagent_subsets_resolve_against_full_registry():
    """三个子 Agent 的 tool_names 都能在全量 registry 上成功切片（名字对得上）。"""
    full = build_default_registry()
    for agent in (APPOINTMENT_SUBAGENT, CONSULTANT_SUBAGENT, USER_BEHAVIOR_SUBAGENT):
        sub = full.subset(list(agent.tool_names))
        assert set(sub.names()) == set(agent.tool_names)


@pytest.mark.asyncio
async def test_specialized_subagent_runs_with_direct_reply():
    """子 Agent 在 fake LLM 直接回复时返回文本，不触碰 services/。"""
    full = build_default_registry()
    llm = ScriptedChatModel(responses=[AIMessage(content="为您查到相关信息。")])
    result = await CONSULTANT_SUBAGENT.run("项目有哪些", full, llm)
    assert result == "为您查到相关信息。"


# --------------------------------------------------------------------------- #
# 5.2 delegate 工具
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_delegate_dispatches_to_subagent():
    full = build_default_registry()
    subagents = build_default_subagent_registry()
    llm = ScriptedChatModel(responses=[AIMessage(content="咨询已解答。")])
    delegate = build_delegate_tool(llm, full, subagents)

    out = await delegate.run({"subagent": "consultant", "task": "问价格"})

    assert out == {"success": True, "subagent": "consultant", "result": "咨询已解答。"}


@pytest.mark.asyncio
async def test_delegate_unknown_subagent_returns_structured_error():
    full = build_default_registry()
    subagents = build_default_subagent_registry()
    llm = ScriptedChatModel(responses=[AIMessage(content="x")])
    delegate = build_delegate_tool(llm, full, subagents)

    out = await delegate.run({"subagent": "ghost", "task": "x"})

    assert out["success"] is False
    assert "ghost" in out["error"]


def test_delegate_description_lists_subagents():
    full = build_default_registry()
    subagents = build_default_subagent_registry()
    delegate = build_delegate_tool(object(), full, subagents)
    for name in ("appointment", "consultant", "user_behavior"):
        assert name in delegate.description


# --------------------------------------------------------------------------- #
# 8.2 主 Agent 经 delegate 自主派生端到端
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_main_agent_delegates_end_to_end():
    full = build_default_registry()
    subagents = build_default_subagent_registry()
    # 共享同一 scripted llm：主 step1 派生 → 子 Agent 直接回复 → 主 step2 终复。
    llm = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call("delegate", {"subagent": "appointment", "task": "约明天"}, "c1")
                ],
            ),
            AIMessage(content="子任务完成。"),  # 子 Agent 的直接回复
            AIMessage(content="已为您安排妥当。"),  # 主 Agent 最终回复
        ]
    )
    delegate = build_delegate_tool(llm, full, subagents)
    main = ToolRegistry()
    main.register(delegate)
    seen: list[str] = []
    loop = AgentLoop(
        llm=llm,
        registry=main,
        system_prompt=build_system_prompt(_DOMAIN.system_prompt, main, subagents),
        on_tool_call=lambda call: seen.append(call["name"]),
    )

    out = "".join([tok async for tok in loop.run("帮我约明天的技师")])

    assert out == "[REPLY]已为您安排妥当。"
    assert seen == ["delegate"]  # 主 Agent 经 delegate 派生，无硬编码路由


@pytest.mark.asyncio
async def test_main_agent_without_delegate_behaves_like_before():
    """不含 delegate 的全量扁平 registry：直接回复路径行为与既有一致。"""
    full = build_default_registry()
    llm = ScriptedChatModel(responses=[AIMessage(content="您好。")])
    loop = AgentLoop(llm=llm, registry=full)

    out = "".join([tok async for tok in loop.run("你好")])

    assert out == "[REPLY]您好。"
