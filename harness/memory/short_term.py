"""短期记忆：最近 N 轮对话窗口（Phase 4：状态与记忆）。

把会话历史（``list[Turn]``）裁剪为最近 N 轮，并转换为 LangChain ``BaseMessage``
列表，供 ``AgentLoop`` 注入到 system prompt 之后、当前 user message 之前。

窗口裁剪与循环编排解耦（一个概念一个文件），便于单测。超出窗口的较旧回合不注入
LLM 上下文（仍可被持久化保留）。详见 OpenSpec change phase-4-state-memory design.md D2。
"""

from __future__ import annotations

from typing import List, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from harness.runtime.session import Turn


class ShortTermMemory:
    """把对话历史裁剪为最近 N 轮并转为消息列表。

    Args:
        window_turns: 窗口轮数（一轮 = 一条消息记录）。默认 10。
    """

    def __init__(self, window_turns: int = 10) -> None:
        self.window_turns = window_turns

    def to_messages(self, history: Sequence[Turn]) -> List[BaseMessage]:
        """返回最近 ``window_turns`` 条历史对应的 BaseMessage 列表。

        user → HumanMessage，assistant → AIMessage；未知 role 跳过。
        """
        recent = history[-self.window_turns:] if self.window_turns > 0 else []
        messages: List[BaseMessage] = []
        for turn in recent:
            if turn.role == "user":
                messages.append(HumanMessage(content=turn.content))
            elif turn.role == "assistant":
                messages.append(AIMessage(content=turn.content))
        return messages
