"""本轮被中断时的会话历史完整性（change: feishu-channel-integration，tasks 1.4）。

编排层的写入顺序是「先写 user 回合 → 驱动 loop → 再写 assistant 回合」。任务在中途被
取消（executor 的墙钟超时）或消费方提前退出（客户端断连）时，若就此走人，库里会留下一条
永远配不上回复的孤立 user 回合——而「历史成对」是 ``ShortTermMemory`` 与摘要压缩的隐含
前提。破了它，下一轮模型会看到一句没人回的话；用户重问后历史里还会出现连排的重复 user
消息。本组用例把「补写兜底回合 + 取消信号继续传播」两条钉死。
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, List

import pytest

import api.chat_handler as ch
from harness.memory.long_term import LongTermMemory
from harness.runtime.session import SessionStore


class _NoopSummaryMemory:
    def get_read_context(self, session_id: str):
        raise NotImplementedError("offline noop")

    def get_summary_hint(self, session_id: str) -> str:
        return ""

    async def compact_if_needed(self, session_id: str) -> None:
        return None


class _StallingLoop:
    """替身 AgentLoop：先吐一个 thought，然后无限期停在 await 点上。"""

    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def run(self, user_input: str, **kwargs: Any) -> AsyncGenerator[str, None]:
        yield "[THOUGHT]思考中"
        self.entered.set()
        await asyncio.sleep(3600)   # 可被取消的 await 点
        yield "[REPLY]永远到不了"


@pytest.fixture
def offline(monkeypatch):
    loop = _StallingLoop()
    monkeypatch.setattr(ch, "_agent_loop", loop)
    monkeypatch.setattr(ch, "_session_store", SessionStore(repo=None))
    monkeypatch.setattr(ch, "_long_term", LongTermMemory(None))
    monkeypatch.setattr(ch, "_summary", _NoopSummaryMemory())
    return loop


def history(session_id: str) -> List[tuple[str, str]]:
    return [(t.role, t.content) for t in ch._session_store.get_or_create(session_id).history]


@pytest.mark.asyncio
async def test_cancellation_writes_fallback_turn_and_propagates(offline):
    """墙钟超时取消：补写兜底 assistant 回合，且 CancelledError 继续向上传播。

    重抛是关键——吞掉取消信号会让 executor 把被中断的任务误判为正常完成。
    """
    async def _consume():
        async for _ in ch.ProcessUserInput_stream("帮我约一下", session_id="s-cancel"):
            pass

    task = asyncio.create_task(_consume())
    await asyncio.wait_for(offline.entered.wait(), timeout=2.0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert history("s-cancel") == [
        ("user", "帮我约一下"),
        ("assistant", ch._DEFAULT_INTERRUPTED_REPLY),
    ]


@pytest.mark.asyncio
async def test_consumer_disconnect_also_keeps_history_paired(offline):
    """客户端断连（生成器被 aclose）同样补写兜底回合，不留孤立 user 回合。"""
    agen = ch.ProcessUserInput_stream("在吗", session_id="s-disconnect")
    assert await agen.__anext__() == "[THOUGHT]思考中"
    await agen.aclose()

    assert history("s-disconnect") == [
        ("user", "在吗"),
        ("assistant", ch._DEFAULT_INTERRUPTED_REPLY),
    ]


@pytest.mark.asyncio
async def test_caller_supplied_text_is_used(offline):
    """兜底回合用调用方传入的文案——与实际投递给用户的那句保持一致。"""
    agen = ch.ProcessUserInput_stream(
        "在吗", session_id="s-text", interrupted_reply="处理超时了，请勿重复下单。"
    )
    await agen.__anext__()
    await agen.aclose()

    assert history("s-text")[-1] == ("assistant", "处理超时了，请勿重复下单。")


@pytest.mark.asyncio
async def test_no_double_write_on_normal_completion(monkeypatch):
    """正常完成路径不受影响：assistant 回合只写一条。"""
    class _NormalLoop:
        async def run(self, user_input: str, **kwargs: Any) -> AsyncGenerator[str, None]:
            yield "[REPLY]好的。"

    monkeypatch.setattr(ch, "_agent_loop", _NormalLoop())
    monkeypatch.setattr(ch, "_session_store", SessionStore(repo=None))
    monkeypatch.setattr(ch, "_long_term", LongTermMemory(None))
    monkeypatch.setattr(ch, "_summary", _NoopSummaryMemory())

    async for _ in ch.ProcessUserInput_stream("你好", session_id="s-ok"):
        pass

    assert history("s-ok") == [("user", "你好"), ("assistant", "好的。")]


@pytest.mark.asyncio
async def test_user_id_is_passed_to_session_store(monkeypatch):
    """群聊身份透传：user_id 落到 SessionState，长期偏好据此按人读取。"""
    class _NormalLoop:
        async def run(self, user_input: str, **kwargs: Any) -> AsyncGenerator[str, None]:
            yield "[REPLY]好的。"

    monkeypatch.setattr(ch, "_agent_loop", _NormalLoop())
    monkeypatch.setattr(ch, "_session_store", SessionStore(repo=None))
    monkeypatch.setattr(ch, "_long_term", LongTermMemory(None))
    monkeypatch.setattr(ch, "_summary", _NoopSummaryMemory())

    async for _ in ch.ProcessUserInput_stream("你好", session_id="s-uid", user_id="ou_abc"):
        pass

    assert ch._session_store.get_or_create("s-uid").user_id == "ou_abc"


@pytest.mark.asyncio
async def test_web_path_keeps_default_user(monkeypatch):
    """Web 不传 user_id 时沿用默认用户——行为不变。"""
    class _NormalLoop:
        async def run(self, user_input: str, **kwargs: Any) -> AsyncGenerator[str, None]:
            yield "[REPLY]好的。"

    monkeypatch.setattr(ch, "_agent_loop", _NormalLoop())
    monkeypatch.setattr(ch, "_session_store", SessionStore(repo=None))
    monkeypatch.setattr(ch, "_long_term", LongTermMemory(None))
    monkeypatch.setattr(ch, "_summary", _NoopSummaryMemory())

    async for _ in ch.ProcessUserInput_stream("你好", session_id="s-web"):
        pass

    assert ch._session_store.get_or_create("s-web").user_id == "default_user"
