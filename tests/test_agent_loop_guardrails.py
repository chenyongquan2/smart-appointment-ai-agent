"""AgentLoop 在护栏下的离线确定性单测（Phase 5）。

覆盖：LLM 持续失败时优雅降级、token 预算终止、打转终止、权限拒绝结果回灌、
以及"副作用工具不被 LLM 重试护栏波及"。全程不触网。
"""

from __future__ import annotations

from typing import Any, List, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel

from harness.guardrails.permission import Decision
from harness.runtime import AgentLoop
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class ScriptedChatModel(BaseChatModel):
    """按预设序列返回 AIMessage；脚本耗尽则继续返回最后一条。"""

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


class FailingChatModel(BaseChatModel):
    """每次调用都抛可重试异常（模拟 LLM 持续失败）。"""

    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "failing-chat-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FailingChatModel":
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        object.__setattr__(self, "calls", self.calls + 1)
        raise ConnectionError("LLM 持续不可用")


def _tool_call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


async def _noop_sleep(_d: float) -> None:
    return None


async def _collect(loop: AgentLoop, user_input: str) -> str:
    return "".join([tok async for tok in loop.run(user_input)])


class _EchoArgs(BaseModel):
    value: str = ""


def _make_registry(**kwargs) -> tuple[ToolRegistry, list[str]]:
    log: list[str] = []

    async def _echo(args: _EchoArgs) -> str:
        log.append(f"echo:{args.value}")
        return f"echo<{args.value}>"

    reg = ToolRegistry(**kwargs)
    reg.register(Tool("echo", "回显输入", _EchoArgs, _echo))
    return reg, log


# --------------------------------------------------------------------------- #
# LLM 持续失败 → 优雅降级（不抛异常）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_llm_failure_degrades_gracefully():
    reg, log = _make_registry()
    llm = FailingChatModel()
    loop = AgentLoop(
        llm=llm,
        registry=reg,
        llm_max_attempts=2,
        retry_sleep=_noop_sleep,  # 不真睡
    )

    out = await _collect(loop, "你好")

    assert out.startswith("[REPLY]")
    assert "无法完成" in out  # 兜底回复，未崩溃
    assert llm.calls == 2  # 恰好重试 max_attempts 次
    assert log == []


# --------------------------------------------------------------------------- #
# token 预算终止
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_token_budget_terminates_before_llm_call():
    reg, log = _make_registry()
    llm = ScriptedChatModel(responses=[AIMessage(content="本应给出的回复")])
    # max_tokens=1：system prompt 早已远超预算，首步即终止，绝不调用 LLM。
    loop = AgentLoop(llm=llm, registry=reg, max_tokens=1)

    out = await _collect(loop, "你好")

    assert out.startswith("[REPLY]")
    assert "无法完成" in out
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_token_budget_sufficient_does_not_interfere():
    reg, log = _make_registry()
    llm = ScriptedChatModel(responses=[AIMessage(content="正常回复")])
    loop = AgentLoop(llm=llm, registry=reg, max_tokens=1_000_000)

    out = await _collect(loop, "你好")

    assert out == "[REPLY]正常回复"
    assert llm.calls == 1


# --------------------------------------------------------------------------- #
# 打转终止
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_spin_terminates_loop():
    reg, log = _make_registry()
    # 始终返回完全相同的工具调用 → repeat_limit=3 时第三步判定打转。
    llm = ScriptedChatModel(
        responses=[AIMessage(content="", tool_calls=[_tool_call("echo", {"value": "z"}, "c1")])]
    )
    loop = AgentLoop(llm=llm, registry=reg, max_steps=8, repeat_limit=3)

    out = await _collect(loop, "卡死")

    assert out.startswith("[REPLY]")
    assert "无法完成" in out
    assert llm.calls == 3  # 早于 max_steps=8 终止
    assert log == ["echo:z", "echo:z"]  # 前两步执行，第三步打转前终止


# --------------------------------------------------------------------------- #
# 权限拒绝结果回灌 → 不执行 handler、不崩、继续到最终回复
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_permission_denied_result_fed_back():
    log: list[str] = []
    captured: list[tuple[str, Any]] = []

    async def _book(args: _EchoArgs) -> str:
        log.append("book")  # 不应被执行
        return "booked"

    def deny(tool: Tool, args: dict) -> Decision:
        return Decision.denied("需人工确认")

    reg = ToolRegistry(permission=deny)
    reg.register(Tool("book_appointment", "预约", _EchoArgs, _book, dangerous=True))

    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("book_appointment", {"value": "x"}, "c1")]),
            AIMessage(content="该操作需要确认，请稍后。"),
        ]
    )
    loop = AgentLoop(
        llm=llm, registry=reg,
        on_observation=lambda name, result: captured.append((name, result)),
    )

    out = await _collect(loop, "帮我约")

    assert out == "[REPLY]该操作需要确认，请稍后。"
    assert log == []  # handler 未执行，无副作用
    assert captured and captured[0][1].get("denied") is True


# --------------------------------------------------------------------------- #
# 4.1 工具失败回灌不崩循环（显式回归）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_tool_failure_fed_back_regression():
    log: list[str] = []

    async def _boom(args: _EchoArgs) -> str:
        log.append("boom")
        raise RuntimeError("工具炸了")

    reg = ToolRegistry()
    reg.register(Tool("boom", "抛异常", _EchoArgs, _boom))
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("boom", {}, "c1")]),
            AIMessage(content="已改用其它方式。"),
        ]
    )
    loop = AgentLoop(llm=llm, registry=reg)

    out = await _collect(loop, "触发")

    assert out == "[REPLY]已改用其它方式。"  # 不崩，继续到回复
    assert log == ["boom"]


# --------------------------------------------------------------------------- #
# 4.2 副作用工具失败 NOT 被重试（重试只包裹 LLM 调用）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_side_effect_tool_not_retried_on_failure():
    handler_calls = {"n": 0}

    async def _book(args: _EchoArgs) -> str:
        handler_calls["n"] += 1
        raise RuntimeError("下单失败")

    reg = ToolRegistry()
    reg.register(Tool("create_appointment", "预约", _EchoArgs, _book, dangerous=True))
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("create_appointment", {}, "c1")]),
            AIMessage(content="抱歉，预约未成功。"),
        ]
    )
    # 即便配置了多次重试，工具失败也只发生一次（重试仅作用于 LLM 调用）。
    loop = AgentLoop(
        llm=llm, registry=reg, llm_max_attempts=3, retry_sleep=_noop_sleep
    )

    out = await _collect(loop, "帮我下单")

    assert out == "[REPLY]抱歉，预约未成功。"
    assert handler_calls["n"] == 1  # 副作用工具绝不重试，避免重复下单
