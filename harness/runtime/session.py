"""会话状态与按 session_id 隔离的 SessionStore（Phase 4：状态与记忆）。

取代旧的「模块级单例 + 全局 session_id」：每个 ``session_id`` 拥有独立的
``SessionState``（含对话历史），并以 ``ConversationRepository`` 做持久化，
进程重启后可按同一 session_id 懒加载恢复。

设计要点（见 OpenSpec change phase-4-state-memory 的 design.md D1）：
- 内存 ``Dict`` 缓存热会话，提供并发隔离与低延迟；
- miss 时从 DB 懒加载历史；每轮 append 同时写内存与 DB（重启可恢复）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Turn:
    """一轮对话中的一条消息。role ∈ {'user', 'assistant'}。"""

    # 易误解点：这里的「一轮（Turn）」=「一条消息」，不是「一问一答的一对」。
    # 故一次完整问答会产生两个 Turn：role='user' 一条 + role='assistant' 一条。
    role: str     # 说话方；后续 short_term 据此映射成 HumanMessage / AIMessage
    content: str  # 这条消息的纯文本内容


@dataclass
class SessionState:
    """单个会话的隔离状态。

    Attributes:
        session_id: 会话标识。
        history: 该会话的对话回合（按时间升序）。
        user_id: 关联的用户标识（用于长期偏好读取；缺省沿用 default_user）。
    """

    session_id: str
    # 用 default_factory=list 而非 history=[]：每个 SessionState 实例拿到「自己」的
    # 新列表；若写 `=[]`，所有实例会共享同一个默认列表（Python 可变默认值的经典坑）。
    history: List[Turn] = field(default_factory=list)
    user_id: str = "default_user"  # 缺省用户；长期偏好（long_term）按此 id 跨会话读取


class SessionStore:
    """按 session_id 隔离的会话状态仓库。

    Args:
        repo: ``ConversationRepository``（或鸭子类型等价物），用于历史持久化与
            懒加载。可为 ``None``（纯内存，主要用于测试）。
    """

    def __init__(self, repo=None) -> None:
        self._repo = repo
        # 核心隔离机制：一个 dict，key=session_id，value=该会话独立的 SessionState。
        # 「两个会话为何不串号」就靠它——A、B 各自的 history 存在不同 value 里，互不可见；
        # 取/写历史都先用 session_id 索引到对应 SessionState，天然按会话分桶。
        self._sessions: Dict[str, SessionState] = {}

    def get_or_create(self, session_id: str, user_id: Optional[str] = None) -> SessionState:
        """取出会话状态；不存在则创建，并在有 repo 时从 DB 懒加载历史。"""
        # 先查内存缓存（dict）；命中即「热会话」，直接复用，无需碰 DB（低延迟）。
        state = self._sessions.get(session_id)
        if state is None:
            # 内存 miss：可能是新会话，也可能是「进程刚重启、内存空了」的老会话。
            # _load_history 会去 DB 把历史读回来——这就是「重启恢复」：内存丢了，DB 还在。
            state = SessionState(session_id=session_id, history=self._load_history(session_id))
            if user_id:
                state.user_id = user_id  # 仅在显式传入时覆盖默认 user_id
            self._sessions[session_id] = state  # 放回缓存，下次直接命中
        elif user_id:
            # 已在缓存里：不重建，但若本次带了 user_id 仍更新（同一会话可能补充上用户身份）。
            state.user_id = user_id
        return state

    def append_turn(self, session_id: str, role: str, content: str) -> None:
        """向会话追加一条消息：写内存窗口 + 持久化（若有 repo）。"""
        # 「双写」：同一条 Turn 同时写两处，保证内存与 DB 一致。
        state = self.get_or_create(session_id)
        # ① 写内存：追加到该会话的 history（紧接着的请求就能读到这条，无需等 DB）。
        state.history.append(Turn(role=role, content=content))
        # ② 写 DB：持久化同一条；进程重启后 _load_history 能据此把历史读回（恢复的来源）。
        #    无 repo（纯内存测试场景）时跳过——此时数据只活在内存里，重启即丢，符合预期。
        if self._repo is not None:
            self._repo.append_turn(session_id, role, content)

    def _load_history(self, session_id: str) -> List[Turn]:
        """从持久层读取已有历史（重启恢复）；无 repo 时返回空。"""
        if self._repo is None:
            return []  # 纯内存模式：没有持久层可读，新会话从空历史起步
        # repo 返回的是「行字典」列表（形如 [{"role": ..., "content": ...}, ...]），
        # 这里逐行转回内存用的 Turn dataclass——DB 行 → 领域对象的边界转换。
        rows = self._repo.get_turns(session_id)
        return [Turn(role=r["role"], content=r["content"]) for r in rows]
