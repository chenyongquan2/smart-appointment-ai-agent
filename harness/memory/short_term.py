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
        window_turns: **短期记忆窗口的大小**——保留最近多少条消息原样喂给 LLM。默认 10。
            单位是「条消息」而非「问答对」：一问一答算两条（用户一条 + 助手一条），
            故 window_turns=10 ≈ 最近 5 个来回。
    """

    def __init__(self, window_turns: int = 10) -> None:
        # window_turns = 短期记忆窗口的大小：只把「最近这么多条消息」喂给 LLM。
        # 设小一点能省 token、防上下文爆掉；代价是更早的对话模型「看不到」
        # （但它们仍安静地躺在 DB 里，没被删，可由摘要压缩接住——见 memory/summary.py）。
        self.window_turns = window_turns

    def to_messages(self, history: Sequence[Turn]) -> List[BaseMessage]:
        """返回最近 ``window_turns`` 条历史对应的 BaseMessage 列表。

        user → HumanMessage，assistant → AIMessage；未知 role 跳过。
        """
        # ① 窗口裁剪：history[-N:] 取「末尾 N 条」（即最近 N 轮）。这是整个短期记忆的关键——
        #    窗外的旧轮「不进上下文」，但注意：原始 history 没被改动，旧轮仍在内存/DB 中，
        #    只是这一次没被选进喂给 LLM 的消息里。window_turns<=0 视为「不带任何历史」。
        recent = history[-self.window_turns:] if self.window_turns > 0 else []
        messages: List[BaseMessage] = []
        # ② 形态转换：内存里的 Turn（role/content）→ LangChain 的消息对象，
        #    因为 AgentLoop 喂给 LLM 的是 BaseMessage 列表，不是我们自定义的 Turn。
        for turn in recent:
            if turn.role == "user":
                messages.append(HumanMessage(content=turn.content))      # 顾客说的
            elif turn.role == "assistant":
                messages.append(AIMessage(content=turn.content))         # 助手说的
            # 其它 role（如脏数据/未来扩展）静默跳过，不让异常数据污染上下文。
        return messages
