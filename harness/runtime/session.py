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

    role: str
    content: str


@dataclass
class SessionState:
    """单个会话的隔离状态。

    Attributes:
        session_id: 会话标识。
        history: 该会话的对话回合（按时间升序）。
        user_id: 关联的用户标识（用于长期偏好读取；缺省沿用 default_user）。
    """

    session_id: str
    history: List[Turn] = field(default_factory=list)
    user_id: str = "default_user"


class SessionStore:
    """按 session_id 隔离的会话状态仓库。

    Args:
        repo: ``ConversationRepository``（或鸭子类型等价物），用于历史持久化与
            懒加载。可为 ``None``（纯内存，主要用于测试）。
    """

    def __init__(self, repo=None) -> None:
        self._repo = repo
        self._sessions: Dict[str, SessionState] = {}

    def get_or_create(self, session_id: str, user_id: Optional[str] = None) -> SessionState:
        """取出会话状态；不存在则创建，并在有 repo 时从 DB 懒加载历史。"""
        state = self._sessions.get(session_id)
        if state is None:
            state = SessionState(session_id=session_id, history=self._load_history(session_id))
            if user_id:
                state.user_id = user_id
            self._sessions[session_id] = state
        elif user_id:
            state.user_id = user_id
        return state

    def append_turn(self, session_id: str, role: str, content: str) -> None:
        """向会话追加一条消息：写内存窗口 + 持久化（若有 repo）。"""
        state = self.get_or_create(session_id)
        state.history.append(Turn(role=role, content=content))
        if self._repo is not None:
            self._repo.append_turn(session_id, role, content)

    def _load_history(self, session_id: str) -> List[Turn]:
        """从持久层读取已有历史（重启恢复）；无 repo 时返回空。"""
        if self._repo is None:
            return []
        rows = self._repo.get_turns(session_id)
        return [Turn(role=r["role"], content=r["content"]) for r in rows]
