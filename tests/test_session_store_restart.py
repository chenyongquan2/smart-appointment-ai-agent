"""SessionStore 持久化与重启恢复测试（Phase 4：状态与记忆）。

用临时文件 SQLite 模拟"进程重启"：第一个 SessionStore 写入若干回合后，
新建第二个 SessionStore（指向同一 DB），按同一 session_id 应能恢复历史。
详见 OpenSpec change: phase-4-state-memory。
"""

import pytest

from db.base.session_manager import SessionManager
from db.repositories.conversation_repository import ConversationRepository
from harness.runtime.session import SessionStore


@pytest.fixture
def db_path(tmp_path):
    return f"sqlite:///{tmp_path / 'restart.db'}"


def _store(db_path):
    sm = SessionManager(db_path)
    return SessionStore(repo=ConversationRepository(sm)), sm


def test_history_recovered_after_restart(db_path):
    # 第一个进程：写入两轮
    store1, sm1 = _store(db_path)
    store1.append_turn("s1", "user", "我想预约")
    store1.append_turn("s1", "assistant", "好的，请问什么时间？")
    sm1.close()

    # 模拟重启：全新 SessionStore 指向同一 DB
    store2, sm2 = _store(db_path)
    state = store2.get_or_create("s1")

    assert [(t.role, t.content) for t in state.history] == [
        ("user", "我想预约"),
        ("assistant", "好的，请问什么时间？"),
    ]
    sm2.close()


def test_turn_persisted_to_db(db_path):
    store, sm = _store(db_path)
    store.append_turn("s2", "user", "查价格")

    # 直接经 repo 读回，确认已落库
    rows = ConversationRepository(sm).get_turns("s2")
    assert len(rows) == 1 and rows[0]["content"] == "查价格"
    sm.close()


def test_memory_only_store_has_no_history_on_recreate():
    # 无 repo（纯内存）：新建 store 不应"恢复"任何历史
    store = SessionStore(repo=None)
    store.append_turn("s3", "user", "hi")
    assert len(store.get_or_create("s3").history) == 1

    fresh = SessionStore(repo=None)
    assert fresh.get_or_create("s3").history == []
