"""坏 case 回流数据访问对象（Phase 6：评估闭环）。

薄封装：写入失败/纠正 case、按时间倒序或按 kind 读取，复用既有 ``SessionManager``
事务上下文，风格对齐 ``ConversationRepository``。不重写任何业务逻辑、不改既有业务表。
读取接口 MUST NOT 自动改写 ``evals/cases.jsonl``（增补评估集由人审决定）。
详见 OpenSpec change: phase-6-observability。
"""

from typing import Any, Dict, List, Optional

from ..base.session_manager import SessionManager
from ..models import BadCase

# 合法的 kind 取值。
KIND_FAILURE = "failure"
KIND_CORRECTION = "correction"
_VALID_KINDS = {KIND_FAILURE, KIND_CORRECTION}


class BadCaseRepository:
    """坏 case 数据仓库。

    职责：
    1. 写入一条坏 case（失败或用户纠正）。
    2. 按时间倒序读取最近 N 条；按 kind 过滤读取。
    """

    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager

    def add(
        self,
        kind: str,
        user_input: str,
        expected: Optional[str] = None,
        actual: Optional[str] = None,
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> int:
        """写入一条坏 case，返回新记录 ID。

        Args:
            kind: 'failure'（处理失败）或 'correction'（用户纠正）。
            user_input: 触发的用户输入。
            expected / actual: 期望与实际（均可空）。
            trace_id: 关联的可观测 trace（可空）。
            session_id: 关联会话（可空）。
            extra: 附加结构化信息（JSON，可空）。
        """
        if kind not in _VALID_KINDS:
            raise ValueError(f"非法 kind={kind!r}；必须是 {sorted(_VALID_KINDS)} 之一")
        with self.session_manager.session_scope() as session:
            row = BadCase(
                kind=kind,
                user_input=user_input,
                expected=expected,
                actual=actual,
                trace_id=trace_id,
                session_id=session_id,
                extra=extra,
            )
            session.add(row)
            session.flush()
            return row.id

    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        """按 ``created_at`` 倒序返回最近 ``limit`` 条。"""
        with self.session_manager.session_scope() as session:
            rows = (
                session.query(BadCase)
                .order_by(BadCase.created_at.desc(), BadCase.id.desc())
                .limit(limit)
                .all()
            )
            return [self._to_dict(r) for r in rows]

    def list_by_kind(self, kind: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """按 kind 过滤，按时间倒序返回（可限制条数）。"""
        with self.session_manager.session_scope() as session:
            query = (
                session.query(BadCase)
                .filter(BadCase.kind == kind)
                .order_by(BadCase.created_at.desc(), BadCase.id.desc())
            )
            if limit is not None:
                query = query.limit(limit)
            return [self._to_dict(r) for r in query.all()]

    def _to_dict(self, row: BadCase) -> Dict[str, Any]:
        return {
            "id": row.id,
            "kind": row.kind,
            "user_input": row.user_input,
            "expected": row.expected,
            "actual": row.actual,
            "trace_id": row.trace_id,
            "session_id": row.session_id,
            "extra": row.extra,
            "created_at": row.created_at,
        }
