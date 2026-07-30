"""工具调用超时的离线确定性单测（change: feishu-channel-integration）。

覆盖：超时按错误结果回灌且不重试、工具自身声明覆盖全局缺省、``NO_TIMEOUT`` 豁免
（`delegate` 这类 handler 内部是整个子 AgentLoop 的编排型工具靠它免于被误杀）、
以及「外层取消不被 ``except Exception`` 吞掉」。全程不触网、用极小超时值不真等。
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel

from harness.runtime import AgentLoop
from harness.tools.base import NO_TIMEOUT, Tool
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
        object.__setattr__(self, "calls", self.calls + 1)
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])


class _Args(BaseModel):
    pass


def _slow_tool(name: str, delay: float = 5.0, **kwargs: Any) -> tuple[Tool, dict]:
    """构造一个「慢工具」，并附一个记录实际调用次数的计数器。"""
    counter = {"calls": 0}

    async def _handler(args: _Args) -> str:
        counter["calls"] += 1
        await asyncio.sleep(delay)  # 有 await 点 → 可被 wait_for 真正中断
        return "不该到这里"

    return Tool(name=name, description="慢工具", args_schema=_Args,
                handler=_handler, **kwargs), counter


def _call(name: str, call_id: str = "c1") -> dict:
    return {"name": name, "args": {}, "id": call_id}


def _loop_with(tool: Tool, **loop_kwargs: Any) -> AgentLoop:
    registry = ToolRegistry()
    registry.register(tool)
    # LLM 不参与本组断言（直接测 _dispatch），给个最简脚本即可。
    llm = ScriptedChatModel(responses=[AIMessage(content="done")])
    return AgentLoop(llm=llm, registry=registry, **loop_kwargs)


# --------------------------------------------------------------------------- #
# 超时回灌与不重试
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_tool_timeout_returned_as_error_result():
    """超时被中断，回灌一条可读的「工具超时」错误结果，而不是抛异常崩掉循环。"""
    tool, _ = _slow_tool("slow")
    loop = _loop_with(tool, tool_timeout=0.01)

    result = await loop._dispatch(_call("slow"))

    assert isinstance(result, str)
    assert "超时" in result and "slow" in result
    assert "不会重试" in result  # 措辞要让模型知道别指望系统自动重发


@pytest.mark.asyncio
async def test_timed_out_tool_is_not_retried():
    """超时的工具 MUST NOT 被自动再次调用——它可能有副作用，重试等于重复执行。"""
    tool, counter = _slow_tool("slow")
    loop = _loop_with(tool, tool_timeout=0.01)

    await loop._dispatch(_call("slow"))

    assert counter["calls"] == 1


# --------------------------------------------------------------------------- #
# 超时值的来源优先级
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_tool_declared_timeout_overrides_global_default():
    """工具自身声明的 timeout 覆盖 loop 的全局缺省。"""
    tool, _ = _slow_tool("slow", timeout=0.01)
    loop = _loop_with(tool, tool_timeout=100.0)  # 全局缺省很宽松

    result = await loop._dispatch(_call("slow"))

    assert "超时" in result  # 仍被工具自身的 0.01s 掐断


@pytest.mark.asyncio
async def test_no_timeout_tool_is_exempt():
    """声明 NO_TIMEOUT 的工具豁免超时——delegate 靠这条免于被全局缺省误杀。"""
    tool, _ = _slow_tool("orchestrator", delay=0.05, timeout=NO_TIMEOUT)
    loop = _loop_with(tool, tool_timeout=0.01)  # 全局缺省远小于该工具耗时

    result = await asyncio.wait_for(loop._dispatch(_call("orchestrator")), timeout=2.0)

    assert result == "不该到这里"  # 正常跑完，未被中断


@pytest.mark.asyncio
async def test_global_default_none_disables_timeout():
    """loop 的全局缺省为 None 时不设超时（向后兼容：接入超时前的行为）。"""
    tool, _ = _slow_tool("slow", delay=0.05)
    loop = _loop_with(tool, tool_timeout=None)

    result = await asyncio.wait_for(loop._dispatch(_call("slow")), timeout=2.0)

    assert result == "不该到这里"


@pytest.mark.asyncio
async def test_delegate_tool_declares_exemption():
    """真实的 delegate 工具（而非替身）确实声明了超时豁免。

    这条断言的是接线而非机制：主 registry 只注册 delegate 一个工具，
    若它漏了豁免，主 Agent 的每次派生都会被 60s 缺省截断。
    """
    from harness.subagents import build_default_subagent_registry, build_delegate_tool
    from harness.tools.registry import build_default_registry

    llm = ScriptedChatModel(responses=[AIMessage(content="done")])
    delegate = build_delegate_tool(llm, build_default_registry(),
                                   build_default_subagent_registry())

    assert delegate.timeout == NO_TIMEOUT


# --------------------------------------------------------------------------- #
# 边界：取消信号不被吞
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_outer_cancellation_propagates():
    """外层任务被取消（如 executor 的墙钟超时）时，CancelledError MUST 继续传播。

    ``_dispatch`` 的 ``except Exception`` 之所以吞不掉它，是因为 ``CancelledError``
    继承自 ``BaseException``。若哪天被误改成 ``except BaseException``，executor 会把
    被取消的任务误判为「工具返回了一条错误结果」而继续跑下去。
    """
    tool, _ = _slow_tool("slow", delay=5.0)
    loop = _loop_with(tool, tool_timeout=None)

    task = asyncio.create_task(loop._dispatch(_call("slow")))
    await asyncio.sleep(0)  # 让 task 真正起跑并停在 sleep 的 await 点上
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


# --------------------------------------------------------------------------- #
# 边界：同步阻塞工具不可中断（记录已知局限，防日后误以为有保护）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_sync_blocking_handler_is_not_interrupted():
    """同步阻塞的 handler 即使声明了 timeout 也不会被中断——这是已知边界，不是 bug。

    ``asyncio.wait_for`` 只能在 await 点取消协程。handler 内部若跑同步阻塞调用
    （同步 SQLite / FAISS / 子进程），到点也掐不断。需要真超时的同步工具必须自行
    ``asyncio.to_thread``。本测试把该局限钉死，避免第 3 期移植网络工具时误判。
    """
    import time

    async def _handler(args: _Args) -> str:
        time.sleep(0.05)  # 故意用同步 sleep：无 await 点，取消不掉
        return "跑完了"

    tool = Tool(name="blocking", description="同步阻塞工具",
                args_schema=_Args, handler=_handler)
    loop = _loop_with(tool, tool_timeout=0.001)

    result = await loop._dispatch(_call("blocking"))

    assert result == "跑完了"  # 声明了 1ms 超时，仍然完整跑完


# --------------------------------------------------------------------------- #
# 未注册工具：仍走原有错误回灌路径
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_unknown_tool_still_feeds_back_error():
    """未注册的工具名不因超时解析而改变行为，仍回灌「工具执行失败」。"""
    tool, _ = _slow_tool("slow")
    loop = _loop_with(tool, tool_timeout=1.0)

    result = await loop._dispatch(_call("nope"))

    assert "工具执行失败" in result and "nope" in result
