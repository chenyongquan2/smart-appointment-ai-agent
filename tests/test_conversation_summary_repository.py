"""ConversationSummaryRepository 单测（add-context-compaction：记忆压缩）。

用临时文件 SQLite（tmp_path）验证 get/upsert（插入+更新）、按 session 隔离、
不存在返回 None。不触网、不依赖既有数据库文件。
详见 OpenSpec change: add-context-compaction。
"""

import pytest

from db.base.session_manager import SessionManager
from db.repositories.conversation_summary_repository import ConversationSummaryRepository


@pytest.fixture
def repo(tmp_path):
    db_path = f"sqlite:///{tmp_path / 'summary.db'}"
    sm = SessionManager(db_path)
    yield ConversationSummaryRepository(sm)
    sm.close()


def test_get_missing_returns_none(repo):
    assert repo.get_summary("nope") is None


def test_upsert_then_get_roundtrip(repo):
    repo.upsert_summary("s1", "顾客偏好女技师；周末时段", covered_upto=12)

    row = repo.get_summary("s1")

    assert row is not None
    assert row["summary_text"] == "顾客偏好女技师；周末时段"
    assert row["covered_upto"] == 12


def test_upsert_updates_existing_in_place(repo):
    repo.upsert_summary("s1", "旧摘要", covered_upto=5)
    repo.upsert_summary("s1", "新摘要（滚动并入更多回合）", covered_upto=20)

    row = repo.get_summary("s1")

    # 同一会话只保留最新一条（覆盖更新，不堆历史快照）。
    assert row["summary_text"] == "新摘要（滚动并入更多回合）"
    assert row["covered_upto"] == 20


def test_isolated_by_session(repo):
    repo.upsert_summary("s1", "会话1摘要", covered_upto=3)
    repo.upsert_summary("s2", "会话2摘要", covered_upto=7)

    assert repo.get_summary("s1")["summary_text"] == "会话1摘要"
    assert repo.get_summary("s2")["summary_text"] == "会话2摘要"
