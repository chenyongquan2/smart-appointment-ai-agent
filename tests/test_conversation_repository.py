"""ConversationRepository 单测（Phase 4：会话历史持久化）。

用临时文件 SQLite（tmp_path）验证 append→get 读回、按 session 隔离、limit 取最近 N。
不触网、不依赖既有数据库文件。详见 OpenSpec change: phase-4-state-memory。
"""

import pytest

from db.base.session_manager import SessionManager
from db.repositories.conversation_repository import ConversationRepository


@pytest.fixture
def repo(tmp_path):
    db_path = f"sqlite:///{tmp_path / 'conv.db'}"
    sm = SessionManager(db_path)
    yield ConversationRepository(sm)
    sm.close()


def test_append_then_get_roundtrip(repo):
    repo.append_turn("s1", "user", "你好")
    repo.append_turn("s1", "assistant", "您好，有什么可以帮您？")

    turns = repo.get_turns("s1")

    assert [(t["role"], t["content"]) for t in turns] == [
        ("user", "你好"),
        ("assistant", "您好，有什么可以帮您？"),
    ]


def test_isolated_by_session(repo):
    repo.append_turn("s1", "user", "约一下")
    repo.append_turn("s2", "user", "查价格")

    s1 = repo.get_turns("s1")
    s2 = repo.get_turns("s2")

    assert len(s1) == 1 and s1[0]["content"] == "约一下"
    assert len(s2) == 1 and s2[0]["content"] == "查价格"


def test_limit_returns_recent_in_ascending_order(repo):
    for i in range(6):
        repo.append_turn("s1", "user", f"m{i}")

    recent = repo.get_turns("s1", limit=3)

    # 最近 3 条，仍按时间升序排列
    assert [t["content"] for t in recent] == ["m3", "m4", "m5"]


def test_empty_session_returns_empty(repo):
    assert repo.get_turns("nope") == []
