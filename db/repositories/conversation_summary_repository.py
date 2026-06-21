"""会话摘要缓存数据访问对象（add-context-compaction：记忆压缩）。

薄封装：按 ``session_id`` 读取/写入（upsert）一条滚动摘要，复用既有
``SessionManager`` 的事务上下文，风格对齐 ``ConversationRepository``。
不重写任何业务逻辑。详见 OpenSpec change: add-context-compaction（design.md D5）。
"""

from typing import Any, Dict, Optional

from ..base.session_manager import SessionManager
from ..models import ConversationSummary


class ConversationSummaryRepository:
    """会话摘要缓存数据仓库。

    职责：
    1. 按 session_id 读取当前摘要（含覆盖游标 covered_upto）。
    2. upsert 摘要：存在则更新、不存在则插入（一个会话至多一条）。
    """

    def __init__(self, session_manager: SessionManager):
        """
        Args:
            session_manager: 会话管理器（提供 session_scope 事务上下文）。
        """
        self.session_manager = session_manager

    def get_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """读取某会话的摘要；不存在返回 None。

        Returns:
            含 ``summary_text`` / ``covered_upto`` / ``updated_at`` 的字典，或 None。
        """
        with self.session_manager.session_scope() as session:
            row = (
                session.query(ConversationSummary)
                .filter(ConversationSummary.session_id == session_id)
                .one_or_none()
            )
            if row is None:
                return None
            return self._to_dict(row)

    def upsert_summary(self, session_id: str, summary_text: str, covered_upto: int) -> None:
        """写入或更新某会话的摘要（滚动 upsert，不堆历史快照）。

        Args:
            session_id: 会话 ID
            summary_text: 渲染后的摘要文本
            covered_upto: 书签/游标——本摘要已覆盖到的【末条 turn id】（id ≤ 此值的回合
                信息都已并入 summary_text）。下次压缩据此只处理 id 更大的新出窗回合。
        """
        with self.session_manager.session_scope() as session:
            row = (
                session.query(ConversationSummary)
                .filter(ConversationSummary.session_id == session_id)
                .one_or_none()
            )
            if row is None:
                # 不存在：插入新行。
                session.add(
                    ConversationSummary(
                        session_id=session_id,
                        summary_text=summary_text,
                        covered_upto=covered_upto,
                    )
                )
            else:
                # 存在：原地更新（updated_at 由 onupdate 自动刷新）。
                row.summary_text = summary_text
                row.covered_upto = covered_upto

    def _to_dict(self, row: ConversationSummary) -> Dict[str, Any]:
        """将摘要对象转换为字典。"""
        return {
            'id': row.id,
            'session_id': row.session_id,
            'summary_text': row.summary_text,
            'covered_upto': row.covered_upto,
            'updated_at': row.updated_at,
        }
