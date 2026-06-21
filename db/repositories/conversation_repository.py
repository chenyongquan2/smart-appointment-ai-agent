"""会话历史数据访问对象（Phase 4：会话历史持久化）。

薄封装：按 ``session_id`` 追加/读取对话回合，复用既有 ``SessionManager`` 的
事务上下文，风格对齐 ``UserBehaviorRepository``。不重写任何业务逻辑。
详见 OpenSpec change: phase-4-state-memory。
"""

from typing import Any, Dict, List, Optional

from ..base.session_manager import SessionManager
from ..models import ConversationTurn


class ConversationRepository:
    """会话对话历史数据仓库。

    职责：
    1. 按 session_id 追加单条对话消息（user / assistant）。
    2. 按 session_id 读取历史（可限制只取最近 N 条）。
    """

    def __init__(self, session_manager: SessionManager):
        """
        Args:
            session_manager: 会话管理器（提供 session_scope 事务上下文）。
        """
        self.session_manager = session_manager

    def append_turn(self, session_id: str, role: str, content: str) -> int:
        """追加一条对话消息。

        Args:
            session_id: 会话 ID
            role: 'user' 或 'assistant'
            content: 消息文本

        Returns:
            新创建的回合记录 ID
        """
        with self.session_manager.session_scope() as session:
            turn = ConversationTurn(session_id=session_id, role=role, content=content)
            session.add(turn)
            session.flush()
            return turn.id

    def get_turns(self, session_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """读取某会话的历史，按时间升序返回。

        Args:
            session_id: 会话 ID
            limit: 若指定，只返回最近 limit 条（仍按时间升序排列）

        Returns:
            对话回合列表（每项含 role / content / created_at）
        """
        with self.session_manager.session_scope() as session:
            query = session.query(ConversationTurn).filter(
                ConversationTurn.session_id == session_id
            )
            if limit is not None:
                # 取最近 limit 条：先按时间倒序取，再翻转为升序。
                rows = (
                    query.order_by(ConversationTurn.created_at.desc(), ConversationTurn.id.desc())
                    .limit(limit)
                    .all()
                )
                rows = list(reversed(rows))
            else:
                rows = query.order_by(
                    ConversationTurn.created_at.asc(), ConversationTurn.id.asc()
                ).all()
            return [self._turn_to_dict(row) for row in rows]

    def get_turns_after(self, session_id: str, after_id: int) -> List[Dict[str, Any]]:
        """读取某会话 id 大于 ``after_id`` 的回合，按 id 升序返回。

        供记忆压缩读侧取「尚未被摘要覆盖（id > covered_upto）」的回合原文
        （change: fix-compaction-gap-blindspot）。``after_id=0`` 即返回全部历史。

        Args:
            session_id: 会话 ID
            after_id: 游标；只返回 id 严格大于此值的回合

        Returns:
            对话回合列表（每项含 id / role / content / created_at），按 id 升序。
        """
        with self.session_manager.session_scope() as session:
            rows = (
                session.query(ConversationTurn)
                .filter(
                    ConversationTurn.session_id == session_id,
                    ConversationTurn.id > after_id,
                )
                .order_by(ConversationTurn.id.asc())
                .all()
            )
            return [self._turn_to_dict(row) for row in rows]

    def _turn_to_dict(self, turn: ConversationTurn) -> Dict[str, Any]:
        """将回合对象转换为字典。"""
        return {
            'id': turn.id,
            'session_id': turn.session_id,
            'role': turn.role,
            'content': turn.content,
            'created_at': turn.created_at,
        }
