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


def test_get_turns_after_filters_by_id(repo):
    # 写 4 条，记录各自 id（自增）
    ids = [
        repo.append_turn("s1", "user", "m0"),
        repo.append_turn("s1", "assistant", "m1"),
        repo.append_turn("s1", "user", "m2"),
        repo.append_turn("s1", "assistant", "m3"),
    ]

    # after_id=0：返回全部，按 id 升序
    assert [t["content"] for t in repo.get_turns_after("s1", 0)] == ["m0", "m1", "m2", "m3"]
    # after_id=中间值：只返回其后
    assert [t["content"] for t in repo.get_turns_after("s1", ids[1])] == ["m2", "m3"]
    # after_id=最大 id：返回空
    assert repo.get_turns_after("s1", ids[-1]) == []


def test_get_turns_after_isolated_by_session(repo):
    repo.append_turn("s1", "user", "a")
    repo.append_turn("s2", "user", "b")
    # 仅返回本会话的回合（按 id>0 取全部）
    assert [t["content"] for t in repo.get_turns_after("s1", 0)] == ["a"]
    assert [t["content"] for t in repo.get_turns_after("s2", 0)] == ["b"]
