"""短期/长期记忆单测（Phase 4：状态与记忆）。

离线、无网络、无 DB 依赖（长期记忆用 fake repo）。
详见 OpenSpec change: phase-4-state-memory。
"""

from langchain_core.messages import AIMessage, HumanMessage

from harness.memory.short_term import ShortTermMemory
from harness.memory.long_term import LongTermMemory
from harness.memory.summary import NoOpSummary, SummaryMemory
from harness.runtime.session import Turn


# --------------------------------------------------------------------------- #
# 短期记忆
# --------------------------------------------------------------------------- #
def test_short_term_maps_roles_to_messages():
    history = [Turn("user", "你好"), Turn("assistant", "您好")]
    msgs = ShortTermMemory(window_turns=10).to_messages(history)

    assert isinstance(msgs[0], HumanMessage) and msgs[0].content == "你好"
    assert isinstance(msgs[1], AIMessage) and msgs[1].content == "您好"


def test_short_term_window_truncates_to_recent():
    history = [Turn("user", f"m{i}") for i in range(6)]
    msgs = ShortTermMemory(window_turns=3).to_messages(history)

    assert [m.content for m in msgs] == ["m3", "m4", "m5"]


def test_short_term_empty_history():
    assert ShortTermMemory().to_messages([]) == []


# --------------------------------------------------------------------------- #
# 长期记忆
# --------------------------------------------------------------------------- #
class _FakePrefRepo:
    def __init__(self, prefs):
        self._prefs = prefs

    def get_user_preferences(self, user_id):
        return self._prefs


def test_long_term_builds_hint_from_preferences():
    repo = _FakePrefRepo([
        {"preference_type": "technician", "preference_value": "张三", "confidence_score": 5},
        {"preference_type": "duration", "preference_value": "60分钟", "confidence_score": 3},
    ])
    hint = LongTermMemory(repo).build_preference_hint("u1")

    assert "技师：张三" in hint
    assert "服务时长：60分钟" in hint


def test_long_term_empty_when_no_preferences():
    assert LongTermMemory(_FakePrefRepo([])).build_preference_hint("u1") == ""


def test_long_term_empty_on_repo_error():
    class _Boom:
        def get_user_preferences(self, user_id):
            raise RuntimeError("db down")

    assert LongTermMemory(_Boom()).build_preference_hint("u1") == ""


def test_long_term_no_repo():
    assert LongTermMemory(None).build_preference_hint("u1") == ""


# --------------------------------------------------------------------------- #
# 摘要层占位
# --------------------------------------------------------------------------- #
def test_noop_summary_returns_empty_and_satisfies_protocol():
    s = NoOpSummary()
    assert isinstance(s, SummaryMemory)
    assert s.summarize([Turn("user", "旧消息")]) == ""
