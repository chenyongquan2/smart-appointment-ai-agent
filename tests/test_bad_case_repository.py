"""BadCaseRepository 单测（Phase 6：评估闭环）。

用临时文件 SQLite 验证写读一致、按 kind 过滤、关联 trace_id 持久化、最近 N 倒序。
不触网、不依赖既有数据库文件。详见 OpenSpec change: phase-6-observability。
"""

import pytest

from db.base.session_manager import SessionManager
from db.repositories.bad_case_repository import (
    KIND_CORRECTION,
    KIND_FAILURE,
    BadCaseRepository,
)


@pytest.fixture
def repo(tmp_path):
    db_path = f"sqlite:///{tmp_path / 'bad.db'}"
    sm = SessionManager(db_path)
    yield BadCaseRepository(sm)
    sm.close()


def test_add_then_read_roundtrip(repo):
    repo.add(
        kind=KIND_FAILURE,
        user_input="约一下张三",
        actual="<异常:TimeoutError>",
        trace_id="t-123",
        session_id="s1",
        extra={"step": 3},
    )

    rows = repo.list_recent()
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == KIND_FAILURE
    assert row["user_input"] == "约一下张三"
    assert row["actual"] == "<异常:TimeoutError>"
    assert row["trace_id"] == "t-123"
    assert row["extra"] == {"step": 3}
    assert row["created_at"] is not None


def test_list_by_kind_filters(repo):
    repo.add(kind=KIND_FAILURE, user_input="失败的")
    repo.add(kind=KIND_CORRECTION, user_input="纠正的", expected="appointment", actual="query")

    corrections = repo.list_by_kind(KIND_CORRECTION)
    assert len(corrections) == 1
    assert corrections[0]["user_input"] == "纠正的"
    assert corrections[0]["expected"] == "appointment"

    failures = repo.list_by_kind(KIND_FAILURE)
    assert len(failures) == 1 and failures[0]["user_input"] == "失败的"


def test_list_recent_desc_and_limit(repo):
    for i in range(5):
        repo.add(kind=KIND_FAILURE, user_input=f"case-{i}")

    recent = repo.list_recent(limit=3)
    # 倒序：最后写入的在前。
    assert [r["user_input"] for r in recent] == ["case-4", "case-3", "case-2"]


def test_invalid_kind_rejected(repo):
    with pytest.raises(ValueError):
        repo.add(kind="bogus", user_input="x")


def test_empty_returns_empty(repo):
    assert repo.list_recent() == []
    assert repo.list_by_kind(KIND_FAILURE) == []
