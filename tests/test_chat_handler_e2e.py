"""ProcessUserInput_stream 端到端编排测试（Phase 4：状态与记忆）。

验证真实编排逻辑（chat_handler）按 session 隔离、多轮注入上文、回写历史，
通过 monkeypatch 把模块级单例替换为离线 fake（不触网、不写真实 DB）。
详见 OpenSpec change: phase-4-state-memory。
"""

from typing import Any, List, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import api.chat_handler as ch
from harness.memory.long_term import LongTermMemory
from harness.runtime import AgentLoop
from harness.runtime.session import SessionStore
from harness.tools.registry import ToolRegistry


class CapturingModel(BaseChatModel):
    """记录每次 invoke 收到的 messages，固定回复一句话。"""

    reply: str = "好的。"
    last_messages: List[BaseMessage] = []

    @property
    def _llm_type(self) -> str:
        return "capturing"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "CapturingModel":
        return self

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        object.__setattr__(self, "last_messages", list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.reply))])


class _NoopSummaryMemory:
    """离线占位摘要记忆：读侧恒空、写侧 no-op（不触网/不碰 DB）。"""

    def get_summary_hint(self, session_id: str) -> str:
        return ""

    async def compact_if_needed(self, session_id: str) -> None:
        return None


@pytest.fixture
def offline_handler(monkeypatch):
    """把 chat_handler 的模块级单例替换为离线 fake（内存 SessionStore、无偏好、无压缩）。"""
    llm = CapturingModel()
    loop = AgentLoop(llm=llm, registry=ToolRegistry())
    monkeypatch.setattr(ch, "_agent_loop", loop)
    monkeypatch.setattr(ch, "_session_store", SessionStore(repo=None))
    monkeypatch.setattr(ch, "_long_term", LongTermMemory(None))
    monkeypatch.setattr(ch, "_summary", _NoopSummaryMemory())
    return llm


async def _run(user_input, session_id):
    return "".join(
        [tok async for tok in ch.ProcessUserInput_stream(user_input, session_id=session_id)]
    )


@pytest.mark.asyncio
async def test_same_session_injects_prior_context(offline_handler):
    llm = offline_handler

    await _run("第一轮问题", session_id="s1")
    out2 = await _run("第二轮问题", session_id="s1")

    assert out2 == "[REPLY]好的。"
    # 第二轮 loop 收到的上下文应包含第一轮的 user/assistant
    contents = [m.content for m in llm.last_messages]
    assert "第一轮问题" in contents
    assert "好的。" in contents  # 第一轮的助手回复
    assert contents[-1] == "第二轮问题"  # 当前输入在最后

    # 会话历史累计 4 条（u,a,u,a）
    state = ch._session_store.get_or_create("s1")
    assert [(t.role, t.content) for t in state.history] == [
        ("user", "第一轮问题"),
        ("assistant", "好的。"),
        ("user", "第二轮问题"),
        ("assistant", "好的。"),
    ]


@pytest.mark.asyncio
async def test_two_sessions_isolated(offline_handler):
    llm = offline_handler

    await _run("会话A的问题", session_id="A")
    out_b = await _run("会话B的问题", session_id="B")

    # 会话 B 的上下文不含会话 A 的内容
    contents = [m.content for m in llm.last_messages]
    assert "会话A的问题" not in contents
    assert contents[-1] == "会话B的问题"

    a = ch._session_store.get_or_create("A")
    b = ch._session_store.get_or_create("B")
    assert all("会话B" not in t.content for t in a.history)
    assert all("会话A" not in t.content for t in b.history)


@pytest.mark.asyncio
async def test_session_id_generated_when_absent(offline_handler):
    # 不传 session_id 也应正常工作（内部生成）
    out = "".join([tok async for tok in ch.ProcessUserInput_stream("你好")])
    assert out == "[REPLY]好的。"


@pytest.mark.asyncio
async def test_compaction_runs_after_assistant_writeback(monkeypatch, offline_handler):
    """写侧压缩应在 assistant 回复回写之后触发（inline-after-stream）。"""

    class _RecordingSummary:
        def __init__(self):
            self.snapshot_at_compact = None

        def get_summary_hint(self, session_id):
            return ""

        async def compact_if_needed(self, session_id):
            # 压缩触发时，本轮 user + assistant 都应已落入会话历史。
            state = ch._session_store.get_or_create(session_id)
            self.snapshot_at_compact = [(t.role, t.content) for t in state.history]

    rec = _RecordingSummary()
    monkeypatch.setattr(ch, "_summary", rec)

    await _run("帮我约一下", session_id="s1")

    assert rec.snapshot_at_compact == [
        ("user", "帮我约一下"),
        ("assistant", "好的。"),
    ]
