"""飞书 gateway 的离线确定性单测（change: feishu-channel-integration，tasks 3.4）。

覆盖：@ 判定（含群内其它机器人）、event 去重幂等与 TTL/容量有界、非文本与空正文仍有回复、
会话键绑定、user_id 传递、ack 以 reply 发出且不阻塞回调、畸形事件不炸。

事件对象用轻量替身构造——形状照抄真实载荷
（``docs/evidence/feishu-event-payload-2026-07-29.log``），不触网、不碰真 SDK。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, List, Optional, Tuple

import pytest

from channels.lark.dedup import TTLDedup
from channels.lark.gateway import ACK_REPLY, EMPTY_REPLY, UNSUPPORTED_REPLY, LarkGateway
from channels.lark.parser import parse_message_event
from channels.lark.session_key import SCOPE_CHAT
from db.db_router import DatabaseRouter
from executor import Task, TaskExecutor, TaskStatus

BOT = "ou_e1b205fa92a7a2f66a876563005876ba"
SENDER = "ou_da201dedad6841b88a2acfb4a8601961"
CHAT = "oc_04f2a38ef5f52e59af9da4271442af17"
FIRST_MSG = "om_x100b69419a398ca0c3846178932dd84"
REPLY_MSG = "om_x100b69a3645b9500de343fe093bed79"
THREAD = "omt_1902d586660f1b94"


# --------------------------------------------------------------------------- #
# 事件替身（形状照抄真实载荷）
# --------------------------------------------------------------------------- #
def make_event(
    event_id: str = "evt-1",
    message_id: str = FIRST_MSG,
    text: str = "@_user_1 我想预约",
    message_type: str = "text",
    root_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    mention_open_ids: Tuple[str, ...] = (BOT,),
    sender_open_id: Optional[str] = SENDER,
) -> Any:
    mentions = [
        SimpleNamespace(key=f"@_user_{i + 1}", id=SimpleNamespace(open_id=oid),
                        mentioned_type="bot", name="某机器人")
        for i, oid in enumerate(mention_open_ids)
    ]
    import json as _json
    return SimpleNamespace(
        header=SimpleNamespace(event_id=event_id, event_type="im.message.receive_v1"),
        event=SimpleNamespace(
            sender=SimpleNamespace(sender_id=SimpleNamespace(open_id=sender_open_id)),
            message=SimpleNamespace(
                message_id=message_id, chat_id=CHAT, chat_type="group",
                message_type=message_type, content=_json.dumps({"text": text}),
                root_id=root_id, parent_id=root_id, thread_id=thread_id,
                mentions=mentions,
            ),
        ),
    )


class FakeSender:
    """记录每次投递调用；可配置失败。"""

    def __init__(self, ok: bool = True) -> None:
        self.calls: List[Tuple[str, str]] = []
        self._ok = ok

    async def reply_text(self, message_id: str, text: str) -> bool:
        self.calls.append((message_id, text))
        return self._ok


class RecordingExecutor:
    """只记录 submit 的任务，不真跑——本组测的是 gateway，不是 executor。"""

    def __init__(self) -> None:
        self.tasks: List[Task] = []

    def submit(self, task: Task, on_complete: Any) -> str:
        self.tasks.append(task)
        return "task-id"


@pytest.fixture
def wired():
    sender = FakeSender()
    executor = RecordingExecutor()
    repo = DatabaseRouter("sqlite:///:memory:").channel_sessions
    gw = LarkGateway(
        executor=executor, sender=sender, channel_sessions=repo,
        bot_open_id=BOT, on_complete=lambda result: None,
    )
    return SimpleNamespace(gw=gw, sender=sender, executor=executor, repo=repo)


async def settle() -> None:
    """让 gateway 起的 ack task 跑完（回调是同步的，ack 是异步的）。"""
    await asyncio.sleep(0)
    await asyncio.sleep(0)


# --------------------------------------------------------------------------- #
# @ 判定
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_mention_submits_task_and_acks(wired):
    wired.gw.handle_event(make_event())
    await settle()

    assert len(wired.executor.tasks) == 1
    assert wired.executor.tasks[0].user_input == "我想预约"        # @ 占位符已剔除
    assert wired.sender.calls == [(FIRST_MSG, ACK_REPLY)]


@pytest.mark.asyncio
async def test_other_bot_mention_is_ignored_entirely(wired):
    """@ 的是别的机器人：不提交任务、不回复（这是 spec 要求的静默）。"""
    wired.gw.handle_event(make_event(mention_open_ids=("ou_another_bot",)))
    await settle()

    assert wired.executor.tasks == []
    assert wired.sender.calls == []


@pytest.mark.asyncio
async def test_without_bot_open_id_any_mention_counts(wired):
    """未提供自身 open_id 时退化为「有任何 @ 就算我」——飞书只下发 @ 到本 bot 的群消息。"""
    gw = LarkGateway(
        executor=wired.executor, sender=wired.sender, channel_sessions=wired.repo,
        bot_open_id=None, on_complete=lambda r: None,
    )

    gw.handle_event(make_event(mention_open_ids=("ou_whoever",)))
    await settle()

    assert len(wired.executor.tasks) == 1


# --------------------------------------------------------------------------- #
# 去重
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_duplicate_event_is_processed_once(wired):
    """重复投递只处理一次——否则就是重复下单。"""
    wired.gw.handle_event(make_event(event_id="same"))
    wired.gw.handle_event(make_event(event_id="same"))
    await settle()

    assert len(wired.executor.tasks) == 1
    assert len(wired.sender.calls) == 1  # ack 也只发一次


@pytest.mark.asyncio
async def test_distinct_events_both_processed(wired):
    wired.gw.handle_event(make_event(event_id="e1", message_id="om_1"))
    wired.gw.handle_event(make_event(event_id="e2", message_id="om_2"))
    await settle()

    assert len(wired.executor.tasks) == 2


def test_dedup_expires_after_ttl():
    now = {"t": 1000.0}
    dedup = TTLDedup(ttl_seconds=300.0, clock=lambda: now["t"])

    assert dedup.is_new("k") is True
    assert dedup.is_new("k") is False
    now["t"] += 301.0
    assert dedup.is_new("k") is True  # 已过期，视为没见过


def test_dedup_is_bounded_by_capacity():
    dedup = TTLDedup(max_entries=3, clock=lambda: 0.0)

    for i in range(10):
        dedup.is_new(f"k{i}")

    assert len(dedup) <= 3      # 不无界增长
    assert dedup.is_new("k0")   # 最旧的已被淘汰


# --------------------------------------------------------------------------- #
# 绝不静默：非文本 / 空正文
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_non_text_message_gets_a_hint_not_silence(wired):
    """@ 了机器人却毫无反应，观感等同于坏了——即使本期不处理图片也要回一句。"""
    wired.gw.handle_event(make_event(message_type="image", text=""))
    await settle()

    assert wired.executor.tasks == []
    assert wired.sender.calls == [(FIRST_MSG, UNSUPPORTED_REPLY)]


@pytest.mark.asyncio
async def test_mention_with_no_words_gets_a_hint(wired):
    wired.gw.handle_event(make_event(text="@_user_1"))
    await settle()

    assert wired.executor.tasks == []
    assert wired.sender.calls == [(FIRST_MSG, EMPTY_REPLY)]


# --------------------------------------------------------------------------- #
# 会话绑定与身份
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_reply_chain_shares_one_session(wired):
    """首条与其回复必须落到同一会话——这就是「多轮能用」。"""
    wired.gw.handle_event(make_event(event_id="e1", message_id=FIRST_MSG))
    wired.gw.handle_event(make_event(
        event_id="e2", message_id=REPLY_MSG, root_id=FIRST_MSG, thread_id=THREAD,
    ))
    await settle()

    a, b = wired.executor.tasks
    assert a.session_id == b.session_id == f"feishu:{FIRST_MSG}"
    assert THREAD not in b.session_id  # thread_id 不参与取键


@pytest.mark.asyncio
async def test_independent_mentions_are_isolated(wired):
    wired.gw.handle_event(make_event(event_id="e1", message_id="om_a"))
    wired.gw.handle_event(make_event(event_id="e2", message_id="om_b"))
    await settle()

    a, b = wired.executor.tasks
    assert a.session_id != b.session_id


@pytest.mark.asyncio
async def test_chat_scope_collapses_into_one_session(wired):
    gw = LarkGateway(
        executor=wired.executor, sender=wired.sender, channel_sessions=wired.repo,
        bot_open_id=BOT, on_complete=lambda r: None, session_scope=SCOPE_CHAT,
    )

    gw.handle_event(make_event(event_id="e1", message_id="om_a"))
    gw.handle_event(make_event(event_id="e2", message_id="om_b"))
    await settle()

    a, b = wired.executor.tasks
    assert a.session_id == b.session_id == f"feishu:{CHAT}"


@pytest.mark.asyncio
async def test_sender_open_id_is_passed_as_user_id(wired):
    """群里多人共享会话历史，但长期偏好按人隔离。"""
    wired.gw.handle_event(make_event())
    await settle()

    assert wired.executor.tasks[0].user_id == SENDER


@pytest.mark.asyncio
async def test_binding_is_persisted(wired):
    wired.gw.handle_event(make_event())
    await settle()

    assert wired.repo.find_session_id("feishu", FIRST_MSG) == f"feishu:{FIRST_MSG}"


@pytest.mark.asyncio
async def test_metadata_carries_ack_task_for_ordering(wired):
    """ack task 进 metadata：delivery 投结果前 await 它，使「ack 先于结果」是保证而非侥幸。"""
    wired.gw.handle_event(make_event())
    await settle()

    meta = wired.executor.tasks[0].metadata
    assert meta["message_id"] == FIRST_MSG
    assert meta["chat_id"] == CHAT
    assert isinstance(meta["ack_task"], asyncio.Future)


# --------------------------------------------------------------------------- #
# 回调不阻塞、异常不炸
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_handler_returns_before_ack_completes(wired):
    """回调必须在 ack 真正发出去之前就返回——否则收包循环与协议 ack 都被拖慢。"""
    started = asyncio.Event()

    class SlowSender:
        def __init__(self) -> None:
            self.done = False

        async def reply_text(self, message_id: str, text: str) -> bool:
            started.set()
            await asyncio.sleep(0.05)
            self.done = True
            return True

    slow = SlowSender()
    gw = LarkGateway(
        executor=wired.executor, sender=slow, channel_sessions=wired.repo,
        bot_open_id=BOT, on_complete=lambda r: None,
    )

    gw.handle_event(make_event())          # 同步调用，此处已返回
    assert slow.done is False              # ack 还没发完
    assert len(wired.executor.tasks) == 1  # 但任务已经提交了

    await asyncio.sleep(0.08)
    assert slow.done is True


@pytest.mark.asyncio
async def test_malformed_event_does_not_raise(wired):
    """异常冒回 SDK 会让它把整帧标记为处理失败——必须在 gateway 收口。"""
    wired.gw.handle_event(SimpleNamespace(header=None, event=None))
    wired.gw.handle_event(object())
    await settle()

    assert wired.executor.tasks == []


@pytest.mark.asyncio
async def test_ack_failure_does_not_block_the_task(wired):
    """ack 投递失败只记日志，已提交的任务照跑。"""
    gw = LarkGateway(
        executor=wired.executor, sender=FakeSender(ok=False),
        channel_sessions=wired.repo, bot_open_id=BOT, on_complete=lambda r: None,
    )

    gw.handle_event(make_event())
    await settle()

    assert len(wired.executor.tasks) == 1


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def test_parser_strips_only_mention_placeholders():
    """按 mentions[].key 精确剔除，不能用正则吃掉用户正文里真实的 @。"""
    msg = parse_message_event(make_event(text="@_user_1 帮我查 user@example.com 的预约"))

    assert msg.text == "帮我查 user@example.com 的预约"


def test_parser_returns_none_on_missing_required_fields():
    broken = make_event()
    broken.event.message.chat_id = None

    assert parse_message_event(broken) is None


def test_parser_tolerates_bad_content_json():
    bad = make_event()
    bad.event.message.content = "{不是合法 JSON"

    msg = parse_message_event(bad)

    assert msg is not None and msg.text == ""  # 不抛异常，交由上层回提示


def test_parser_keeps_thread_id_for_diagnostics():
    """thread_id 不参与取键，但要保留——排障时想知道飞书那边是不是话题模式。"""
    msg = parse_message_event(make_event(root_id=FIRST_MSG, thread_id=THREAD))

    assert msg.thread_id == THREAD
    assert msg.root_id == FIRST_MSG
