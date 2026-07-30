"""IM 渠道会话映射数据访问对象（change: feishu-channel-integration）。

薄封装：登记/查询「渠道会话键 → Agent session_id」的绑定，复用既有 ``SessionManager``
的事务上下文，风格对齐 ``ConversationRepository``。不重写任何业务逻辑。
"""

from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError

from ..base.session_manager import SessionManager
from ..models import ChannelSession


class ChannelSessionRepository:
    """渠道会话映射数据仓库。

    职责：
    1. 幂等登记「(channel, external_id) → session_id」绑定。
    2. 按外部键查绑定（供 gateway 复用已有会话）。
    3. 按 session_id 反查外部键（供排障 / 第 4 期 triage 把 trace 关联回真实对话）。
    """

    def __init__(self, session_manager: SessionManager):
        """
        Args:
            session_manager: 会话管理器（提供 session_scope 事务上下文）。
        """
        self.session_manager = session_manager

    def bind(self, channel: str, scope: str, external_id: str, session_id: str) -> str:
        """幂等登记绑定；已存在则返回**已有的** session_id，不覆盖。

        「已存在不覆盖」是本方法的核心语义：表中记录一旦建立即为权威。调用方传入的
        ``session_id`` 只是新建时的候选值（通常由 ``external_id`` 派生），因此日后若调整
        派生规则，既有会话仍按表中记录延续，不会集体断档。

        Args:
            channel: 渠道标识（如 ``feishu``）。
            scope: 会话作用域（``reply`` / ``chat``），仅作记录，不参与唯一性判定。
            external_id: 解析后的会话键。
            session_id: 新建绑定时使用的 Agent 会话标识。

        Returns:
            实际生效的 session_id（已存在时为原值）。
        """
        existing = self.find_session_id(channel, external_id)
        if existing is not None:
            return existing

        try:
            with self.session_manager.session_scope() as session:
                session.add(ChannelSession(
                    channel=channel, scope=scope,
                    external_id=external_id, session_id=session_id,
                ))
            return session_id
        except IntegrityError:
            # 并发下两个协程同时 miss、同时插入：唯一约束会挡下后到的那个。
            # 此时重查一次取胜者的值——绝不能让两条消息拿到不同 session_id（那就串号了）。
            winner = self.find_session_id(channel, external_id)
            return winner if winner is not None else session_id

    def find_session_id(self, channel: str, external_id: str) -> Optional[str]:
        """按 (channel, external_id) 查已绑定的 session_id；未绑定返回 ``None``。"""
        with self.session_manager.session_scope() as session:
            row = (
                session.query(ChannelSession)
                .filter(
                    ChannelSession.channel == channel,
                    ChannelSession.external_id == external_id,
                )
                .first()
            )
            return row.session_id if row is not None else None

    def find_by_session_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        """按 session_id 反查绑定（排障 / trace 关联用）；未找到返回 ``None``。"""
        with self.session_manager.session_scope() as session:
            row = (
                session.query(ChannelSession)
                .filter(ChannelSession.session_id == session_id)
                .first()
            )
            return self._to_dict(row) if row is not None else None

    def _to_dict(self, row: ChannelSession) -> Dict[str, Any]:
        """将映射对象转换为字典。"""
        return {
            'id': row.id,
            'channel': row.channel,
            'scope': row.scope,
            'external_id': row.external_id,
            'session_id': row.session_id,
            'created_at': row.created_at,
        }
