"""AgentLoop 的离线确定性单测（Phase 3）。

用脚本化的 fake ``BaseChatModel`` 驱动 TAO 循环，覆盖四类路径 + 工具异常回灌，
全程不触网、不依赖 API key（见 OpenSpec change: phase-3-agent-loop）。
"""

from typing import Any, List, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, Field

from harness.runtime import AgentLoop
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry


# --------------------------------------------------------------------------- #
# 脚本化 fake LLM：按预设序列返回 AIMessage（带或不带 tool_calls）。
# --------------------------------------------------------------------------- #
class ScriptedChatModel(BaseChatModel):
    """每次 invoke 弹出脚本里的下一条 AIMessage；脚本耗尽则继续返回最后一条。

    bind_tools 返回自身（忽略工具 schema），使其可被 AgentLoop 绑定后调用。
    """

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


# --------------------------------------------------------------------------- #
# fake 工具 registry：不触碰 services/，结果完全可控。
# --------------------------------------------------------------------------- #
class _EchoArgs(BaseModel):
    value: str = Field(default="")


class _BoomArgs(BaseModel):
    pass


def _make_registry() -> tuple[ToolRegistry, list[str]]:
    """返回 (registry, 调用记录)。echo 回显入参；boom 抛异常。"""
    log: list[str] = []

    async def _echo(args: _EchoArgs) -> str:
        log.append(f"echo:{args.value}")
        return f"echo<{args.value}>"

    async def _boom(args: _BoomArgs) -> str:
        log.append("boom")
        raise RuntimeError("工具内部炸了")

    reg = ToolRegistry()
    reg.register(Tool("echo", "回显输入", _EchoArgs, _echo))
    reg.register(Tool("boom", "总是抛异常", _BoomArgs, _boom))
    return reg, log


async def _collect(loop: AgentLoop, user_input: str) -> str:
    return "".join([tok async for tok in loop.run(user_input)])


# --------------------------------------------------------------------------- #
# 4.2 直接回复路径
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_direct_reply_no_tool_calls():
    reg, log = _make_registry()
    llm = ScriptedChatModel(responses=[AIMessage(content="您好，很高兴为您服务。")])
    loop = AgentLoop(llm=llm, registry=reg)

    out = await _collect(loop, "你好")

    assert out == "[REPLY]您好，很高兴为您服务。"
    assert log == []  # 未调用任何工具
    assert llm.calls == 1


# --------------------------------------------------------------------------- #
# 4.3 单步工具路径
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_single_tool_then_reply():
    reg, log = _make_registry()
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("echo", {"value": "hi"}, "c1")]),
            AIMessage(content="已为您查询完成。"),
        ]
    )
    loop = AgentLoop(llm=llm, registry=reg)

    out = await _collect(loop, "查一下")

    assert out == "[REPLY]已为您查询完成。"
    assert log == ["echo:hi"]
    assert llm.calls == 2


# --------------------------------------------------------------------------- #
# 4.4 多步组合路径（连续两次不同工具调用后回复）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_multi_step_composition():
    reg, log = _make_registry()
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("echo", {"value": "a"}, "c1")]),
            AIMessage(content="", tool_calls=[_tool_call("echo", {"value": "b"}, "c2")]),
            AIMessage(content="已为您预约成功。"),
        ]
    )
    loop = AgentLoop(llm=llm, registry=reg)

    out = await _collect(loop, "约一下")

    assert out == "[REPLY]已为您预约成功。"
    assert log == ["echo:a", "echo:b"]  # 多步按序执行
    assert llm.calls == 3


# --------------------------------------------------------------------------- #
# 同一步多个工具调用全部喂回
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_parallel_tool_calls_in_one_step():
    reg, log = _make_registry()
    llm = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    _tool_call("echo", {"value": "x"}, "c1"),
                    _tool_call("echo", {"value": "y"}, "c2"),
                ],
            ),
            AIMessage(content="完成。"),
        ]
    )
    loop = AgentLoop(llm=llm, registry=reg)

    out = await _collect(loop, "并行")

    assert out == "[REPLY]完成。"
    assert log == ["echo:x", "echo:y"]  # 同一步两个调用都执行
    assert llm.calls == 2  # 一步工具 + 一步回复


# --------------------------------------------------------------------------- #
# 4.5 max_steps 上限生效（始终返回工具调用）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_max_steps_fallback():
    reg, log = _make_registry()
    # 脚本只有「工具调用」一条；耗尽后 ScriptedChatModel 继续返回它 → 永不产出回复。
    llm = ScriptedChatModel(
        responses=[AIMessage(content="", tool_calls=[_tool_call("echo", {"value": "z"}, "c1")])]
    )
    loop = AgentLoop(llm=llm, registry=reg, max_steps=3)

    out = await _collect(loop, "死循环")

    assert out.startswith("[REPLY]")
    assert "无法完成" in out  # 兜底回复
    assert llm.calls == 3  # 恰好 max_steps 次，绝不超出
    assert log == ["echo:z", "echo:z", "echo:z"]


# --------------------------------------------------------------------------- #
# 4.6 工具 dispatch 抛异常 → 错误回灌、循环继续不崩
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_tool_failure_is_fed_back_not_crash():
    reg, log = _make_registry()
    captured: list[tuple[str, Any]] = []
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("boom", {}, "c1")]),
            AIMessage(content="抱歉刚才出了点问题，已为您改用其它方式。"),
        ]
    )
    loop = AgentLoop(
        llm=llm,
        registry=reg,
        on_observation=lambda name, result: captured.append((name, result)),
    )

    out = await _collect(loop, "触发异常")

    # 不崩：循环继续到第二步产出最终回复
    assert out == "[REPLY]抱歉刚才出了点问题，已为您改用其它方式。"
    assert log == ["boom"]
    assert llm.calls == 2
    # 错误被作为观测结果回灌
    assert captured and "工具执行失败" in str(captured[0][1])


# --------------------------------------------------------------------------- #
# trace 钩子被调用
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_trace_hooks_invoked():
    reg, _ = _make_registry()
    seen_calls: list[str] = []
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("echo", {"value": "k"}, "c1")]),
            AIMessage(content="好的。"),
        ]
    )
    loop = AgentLoop(
        llm=llm,
        registry=reg,
        on_tool_call=lambda call: seen_calls.append(call["name"]),
    )

    await _collect(loop, "钩子")

    assert seen_calls == ["echo"]
