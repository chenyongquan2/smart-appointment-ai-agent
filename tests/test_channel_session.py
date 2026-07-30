"""会话键解析与渠道会话映射（change: feishu-channel-integration，tasks 3.3）。

**本组用例的真值来自真实租户实测**，不是从文档推的（载荷见
``docs/evidence/feishu-event-payload-2026-07-29.log``）：

    首条 @bot 消息 ── thread_id 无 / root_id 无 / message_id 有
    对消息的回复  ── thread_id 有 / root_id 有 / message_id 有

其中 `test_thread_id_must_not_win_over_root_id` 是防回归的关键一条：原设计把
``thread_id`` 排在解析链首位，那会让首条与其回复落到不同会话、多轮直接断裂。
"""

from __future__ import annotations

import pytest

from channels.lark import (
    CHANNEL,
    SCOPE_CHAT,
    SCOPE_REPLY,
    IncomingMessage,
    normalize_scope,
    resolve_session_key,
)
from db.db_router import DatabaseRouter

# ── 实测载荷里的真实取值（截断保留可辨识度）────────────────────────────────────
FIRST_MSG_ID = "om_x100b69419a398ca0c3846178932dd84"   # 首条 @bot 消息
REPLY_MSG_ID = "om_x100b69a3645b9500de343fe093bed79"   # 对它的回复
THREAD_ID = "omt_1902d586660f1b94"                     # 回复时飞书自动建的话题
CHAT_ID = "oc_04f2a38ef5f52e59af9da4271442af17"
SENDER = "ou_da201dedad6841b88a2acfb4a8601961"
BOT_OPEN_ID = "ou_e1b205fa92a7a2f66a876563005876ba"


def first_message() -> IncomingMessage:
    """首条 @bot 消息：thread_id / root_id / parent_id 全无（实测）。"""
    return IncomingMessage(
        event_id="evt-1", message_id=FIRST_MSG_ID, chat_id=CHAT_ID, chat_type="group",
        text="你好", sender_open_id=SENDER, mentioned_open_ids=(BOT_OPEN_ID,),
    )


def reply_message() -> IncomingMessage:
    """对首条消息的回复：三个键全有（实测）。"""
    return IncomingMessage(
        event_id="evt-2", message_id=REPLY_MSG_ID, chat_id=CHAT_ID, chat_type="group",
        text="你有什么能力呢？", sender_open_id=SENDER,
        root_id=FIRST_MSG_ID, parent_id=FIRST_MSG_ID, thread_id=THREAD_ID,
        mentioned_open_ids=(BOT_OPEN_ID,),
    )


# --------------------------------------------------------------------------- #
# reply 作用域：多轮能不能成立就看这几条
# --------------------------------------------------------------------------- #
def test_first_message_opens_a_session_from_its_own_id():
    key = resolve_session_key(first_message())

    assert key.external_id == FIRST_MSG_ID
    assert key.session_id == f"{CHANNEL}:{FIRST_MSG_ID}"
    assert key.scope == SCOPE_REPLY


def test_reply_lands_in_the_same_session_as_the_message_it_replies_to():
    """这条就是「多轮能用」的定义。"""
    opener = resolve_session_key(first_message())
    reply = resolve_session_key(reply_message())

    assert reply.session_id == opener.session_id


def test_thread_id_must_not_win_over_root_id():
    """★ 防回归：thread_id 不得排在 root_id 之前。

    原设计的链是 thread_id → root_id → message_id。代入实测载荷：首条没有 thread_id
    只能取 message_id，回复却有 thread_id 会取 omt_...，两者不同 → 多轮断裂。
    这条断言把正确顺序钉死。
    """
    reply = resolve_session_key(reply_message())

    assert reply.external_id == FIRST_MSG_ID          # 取的是 root_id
    assert THREAD_ID not in reply.session_id          # 绝不能是话题 id


def test_independent_mentions_get_separate_sessions():
    """两次各自独立的 @（都不是回复）应当互相隔离。"""
    a = resolve_session_key(first_message())
    b = resolve_session_key(
        IncomingMessage(event_id="evt-3", message_id="om_other", chat_id=CHAT_ID,
                        chat_type="group", text="另一件事", sender_open_id=SENDER)
    )

    assert a.session_id != b.session_id


def test_replies_in_different_chains_are_isolated():
    other_chain = IncomingMessage(
        event_id="evt-4", message_id="om_r2", chat_id=CHAT_ID, chat_type="group",
        text="别的话题", sender_open_id=SENDER, root_id="om_another_opener",
        thread_id="omt_another",
    )

    assert resolve_session_key(reply_message()).session_id != \
        resolve_session_key(other_chain).session_id


# --------------------------------------------------------------------------- #
# chat 作用域
# --------------------------------------------------------------------------- #
def test_chat_scope_collapses_everything_into_one_session():
    opener = resolve_session_key(first_message(), scope=SCOPE_CHAT)
    reply = resolve_session_key(reply_message(), scope=SCOPE_CHAT)

    assert opener.session_id == reply.session_id == f"{CHANNEL}:{CHAT_ID}"
    assert opener.scope == SCOPE_CHAT


@pytest.mark.parametrize("raw,expected", [
    (None, SCOPE_REPLY), ("", SCOPE_REPLY), ("reply", SCOPE_REPLY),
    ("  CHAT ", SCOPE_CHAT), ("thread", SCOPE_REPLY), ("鬼画符", SCOPE_REPLY),
])
def test_scope_config_is_normalized_leniently(raw, expected):
    """作用域来自环境变量，拼错不该让整个 Channel 起不来——退回默认仍是可用行为。

    注意 "thread" 也归到 reply：真话题群的专用作用域尚未实现（无可验证的话题群），
    配了也只能按 reply 跑，宁可行为一致也不要半实现。
    """
    assert normalize_scope(raw) == expected


# --------------------------------------------------------------------------- #
# @bot 判定
# --------------------------------------------------------------------------- #
def test_mention_detection_uses_open_id():
    assert first_message().mentions(BOT_OPEN_ID) is True


def test_other_bot_mention_is_not_mine():
    """群里 @ 的是另一个机器人时不该被认成 @ 我。"""
    msg = IncomingMessage(
        event_id="e", message_id="om_x", chat_id=CHAT_ID, chat_type="group",
        text="找别的 bot", sender_open_id=SENDER,
        mentioned_open_ids=("ou_some_other_bot",),
    )

    assert msg.mentions(BOT_OPEN_ID) is False


# --------------------------------------------------------------------------- #
# 映射表
# --------------------------------------------------------------------------- #
@pytest.fixture
def repo():
    return DatabaseRouter("sqlite:///:memory:").channel_sessions


def test_bind_returns_the_session_id_it_created(repo):
    key = resolve_session_key(first_message())

    bound = repo.bind(CHANNEL, key.scope, key.external_id, key.session_id)

    assert bound == key.session_id
    assert repo.find_session_id(CHANNEL, key.external_id) == key.session_id


def test_bind_is_idempotent_and_never_overwrites(repo):
    """表中记录一旦建立即为权威——派生规则日后调整，既有会话仍延续，不集体断档。"""
    repo.bind(CHANNEL, SCOPE_REPLY, FIRST_MSG_ID, "feishu:原始值")

    again = repo.bind(CHANNEL, SCOPE_REPLY, FIRST_MSG_ID, "feishu:换了个派生规则")

    assert again == "feishu:原始值"


def test_unbound_key_returns_none(repo):
    assert repo.find_session_id(CHANNEL, "om_从未见过") is None


def test_reverse_lookup_for_troubleshooting(repo):
    """从 session_id 反查回飞书侧的会话（第 4 期 triage 要把 trace 关联回真实对话）。"""
    repo.bind(CHANNEL, SCOPE_REPLY, FIRST_MSG_ID, f"{CHANNEL}:{FIRST_MSG_ID}")

    row = repo.find_by_session_id(f"{CHANNEL}:{FIRST_MSG_ID}")

    assert row["external_id"] == FIRST_MSG_ID
    assert row["channel"] == CHANNEL
    assert row["scope"] == SCOPE_REPLY
    assert row["created_at"] is not None


def test_same_external_id_across_channels_does_not_collide(repo):
    """唯一约束是 (channel, external_id)——将来接钉钉时同名键不该互相顶掉。"""
    repo.bind(CHANNEL, SCOPE_REPLY, "shared_id", "feishu:shared_id")
    repo.bind("dingtalk", SCOPE_REPLY, "shared_id", "dingtalk:shared_id")

    assert repo.find_session_id(CHANNEL, "shared_id") == "feishu:shared_id"
    assert repo.find_session_id("dingtalk", "shared_id") == "dingtalk:shared_id"
