"""读侧无夹缝盲区的端到端验证（change: fix-compaction-gap-blindspot）。

用真实 tmp SQLite + 真 LLMSummaryMemory + fake LLM，跑 chat_handler 主路径，
断言：摘要已覆盖的回合以摘要注入、未覆盖回合（含本应落在夹缝的）以原文注入，
不存在「既不在摘要也不在原文」的盲区。不触网。
"""

from typing import Any, List, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import api.chat_handler as ch
from db.db_router import DatabaseRouter
from harness.memory.long_term import LongTermMemory
from harness.memory.summary import LLMSummaryMemory
from harness.runtime import AgentLoop
from harness.runtime.session import SessionStore
from harness.tools.registry import ToolRegistry


class CapturingModel(BaseChatModel):
    """记录每次 invoke 收到的 messages，固定回复一句话。"""

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
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="好的。"))])


async def _run(user_input, session_id):
    return "".join(
        [tok async for tok in ch.ProcessUserInput_stream(user_input, session_id=session_id)]
    )


@pytest.mark.asyncio
async def test_read_side_has_no_blindspot(tmp_path, monkeypatch):
    db = DatabaseRouter(db_path=f"sqlite:///{tmp_path / 'nb.db'}")
    sid = "s1"

    # 播种历史：6 条。摘要将覆盖 id≤4；id 5、6 未覆盖（其中 id5 携带关键细节）。
    db.conversations.append_turn(sid, "user", "我要约推拿")          # id 1
    db.conversations.append_turn(sid, "assistant", "好的")            # id 2
    db.conversations.append_turn(sid, "user", "只要女技师")           # id 3（已被摘要覆盖）
    db.conversations.append_turn(sid, "assistant", "记下了")          # id 4
    db.conversations.append_turn(sid, "user", "约周六14:30")          # id 5（未覆盖→应原文可见）
    db.conversations.append_turn(sid, "assistant", "好的，周六14:30") # id 6
    # 摘要覆盖到 id 4（含早期的「女技师」约束）
    db.summaries.upsert_summary(sid, "早期偏好：女技师 / 推拿", covered_upto=4)

    llm = CapturingModel()
    # window_turns 设大 → compact_if_needed 不触发（out_of_window 为空），避免本测试触碰摘要 LLM。
    summary = LLMSummaryMemory(
        llm=llm, conversations_repo=db.conversations, summaries_repo=db.summaries,
        window_turns=50,
    )
    monkeypatch.setattr(ch, "_summary", summary)
    monkeypatch.setattr(ch, "_session_store", SessionStore(repo=db.conversations))
    monkeypatch.setattr(ch, "_long_term", LongTermMemory(None))
    monkeypatch.setattr(ch, "_agent_loop", AgentLoop(llm=llm, registry=ToolRegistry()))

    await _run("把那个时间提前一小时", session_id=sid)

    contents = [str(m.content) for m in llm.last_messages]
    joined = "\n".join(contents)

    # ① 摘要以 SystemMessage 注入（早期被覆盖的约束在此）
    assert any("早期偏好：女技师" in c for c in contents)
    # ② 未覆盖回合(id5/6)以原文注入——这正是「修复前会落入夹缝盲区」的回合
    assert "约周六14:30" in joined
    # ③ 已覆盖回合(id3「只要女技师」)不以原文重复注入（它在摘要里）
    assert not any(c == "只要女技师" for c in contents)
    # ④ 当前输入在最后
    assert contents[-1] == "把那个时间提前一小时"
