"""长连接消费者的离线确定性单测（change: feishu-channel-integration，tasks 3.6/3.7）。

重点不在"能不能连上"（那要真租户），而在**绕开 SDK 两处循环陷阱后接线是否仍然正确**：

1. 不调 SDK 的 ``start()``（它内部 ``run_until_complete``，在 lifespan 里会抛
   "loop is already running"）；
2. 建连前把 SDK 的模块级 ``loop`` 重绑到当前运行循环——否则收包 task 被投到一个不运行
   的循环上，表现为「连上了但永远收不到事件」且**不报任何错**。第二条是本组最该守的
   回归点：它没有任何自然的失败信号。

以及：自检失败 / 建连失败都不得把主服务带崩。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

import lark_oapi.ws.client as ws_module
from channels.lark.consumer import LarkConsumer, build_consumer_from_env, feishu_enabled
from db.db_router import DatabaseRouter
from executor import Task, TaskExecutor

BOT_INFO = {"app_name": "oncall-bot", "open_id": "ou_bot", "activate_status": 2}


class FakeApiClient:
    """替身 API 客户端：可配置 bot info 与投递结果，全程不触网。"""

    def __init__(self, bot: Optional[dict] = None) -> None:
        self._bot = bot
        self.replies: List[tuple] = []

    async def fetch_bot_info(self):
        return self._bot

    async def reply_text(self, message_id: str, text: str) -> bool:
        self.replies.append((message_id, text))
        return True


class FakeWsClient:
    """替身 ws 客户端：记录调用，不真连。"""

    def __init__(self, connect_error: Optional[Exception] = None) -> None:
        self.connected = False
        self.disconnected = False
        self.ping_started = False
        self._connect_error = connect_error

    async def _connect(self) -> None:
        if self._connect_error is not None:
            raise self._connect_error
        self.connected = True

    async def _ping_loop(self) -> None:
        self.ping_started = True
        await asyncio.sleep(3600)  # 心跳是长期任务，靠 stop() 取消

    async def _disconnect(self) -> None:
        self.disconnected = True


class RecordingExecutor:
    def __init__(self) -> None:
        self.tasks: List[Task] = []

    def submit(self, task: Task, on_complete: Any) -> str:
        self.tasks.append(task)
        return "tid"


def make_consumer(
    bot: Optional[dict] = BOT_INFO,
    ws: Optional[FakeWsClient] = None,
    executor: Optional[Any] = None,
) -> tuple[LarkConsumer, FakeApiClient, FakeWsClient]:
    api = FakeApiClient(bot)
    ws = ws or FakeWsClient()
    consumer = LarkConsumer(
        app_id="cli_fake", app_secret="secret",
        executor=executor or RecordingExecutor(),
        channel_sessions=DatabaseRouter("sqlite:///:memory:").channel_sessions,
        client=api,
        ws_client_factory=lambda handler: ws,
    )
    return consumer, api, ws


# --------------------------------------------------------------------------- #
# 启动与装配
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_start_connects_and_starts_heartbeat():
    consumer, _, ws = make_consumer()

    ok = await consumer.start()
    await asyncio.sleep(0)  # 让心跳 task 起跑

    assert ok is True
    assert ws.connected is True
    assert ws.ping_started is True   # 绕开了 start()，心跳得自己起
    await consumer.stop()


@pytest.mark.asyncio
async def test_gateway_is_wired_with_bot_open_id():
    """自检拿到的 open_id 必须传给 gateway 做 @ 判定。"""
    consumer, _, _ = make_consumer()

    await consumer.start()

    assert consumer.gateway is not None
    assert consumer.gateway._bot_open_id == "ou_bot"
    await consumer.stop()


@pytest.mark.asyncio
async def test_missing_bot_info_still_connects_with_degraded_detection():
    """自检失败不立即放弃：仍建连，@ 判定退化（飞书只下发 @ 到本 bot 的群消息）。"""
    consumer, _, ws = make_consumer(bot=None)

    ok = await consumer.start()

    assert ok is True
    assert ws.connected is True
    assert consumer.gateway._bot_open_id is None
    await consumer.stop()


# --------------------------------------------------------------------------- #
# ★ 事件循环重绑（本组最该守的回归点）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_sdk_loop_is_rebound_to_the_running_loop():
    """SDK 用 import 时抓的模块级 loop 去 create_task 收包循环。

    不重绑的话，那个 task 进了一个不运行的循环——连接显示成功、却永远收不到事件，
    且没有任何报错。这条断言是这类静默故障的唯一哨兵。
    """
    consumer, _, _ = make_consumer()
    # 模拟 import 期抓到的"别的"循环。实测该场景真实存在：SDK 在 import 时
    # 若无当前循环就 new_event_loop()，pytest 下会看到
    # "client.py:32: DeprecationWarning: There is no current event loop"。
    stale = asyncio.new_event_loop()
    ws_module.loop = stale
    try:
        await consumer.start()

        assert ws_module.loop is asyncio.get_running_loop()
    finally:
        await consumer.stop()
        stale.close()


@pytest.mark.asyncio
async def test_start_does_not_call_sdk_start():
    """绝不能调 SDK 的 start()——它内部 run_until_complete，在 lifespan 里会抛异常。"""
    called = {"start": False}

    class WsWithStart(FakeWsClient):
        def start(self) -> None:
            called["start"] = True
            raise AssertionError("不该调用 SDK 的 start()")

    consumer, _, ws = make_consumer(ws=WsWithStart())
    await consumer.start()

    assert called["start"] is False
    await consumer.stop()


# --------------------------------------------------------------------------- #
# 失败不拖垮主服务
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_connect_failure_returns_false_instead_of_raising():
    """Channel 起不来不该让 Web 也起不来。"""
    consumer, _, _ = make_consumer(ws=FakeWsClient(connect_error=RuntimeError("握手失败")))

    ok = await consumer.start()

    assert ok is False


@pytest.mark.asyncio
async def test_missing_credentials_short_circuits():
    consumer = LarkConsumer(
        app_id="", app_secret="",
        executor=RecordingExecutor(),
        channel_sessions=DatabaseRouter("sqlite:///:memory:").channel_sessions,
        client=FakeApiClient(BOT_INFO),
        ws_client_factory=lambda h: FakeWsClient(),
    )

    assert await consumer.start() is False


@pytest.mark.asyncio
async def test_stop_is_safe_before_start():
    consumer, _, _ = make_consumer()

    await consumer.stop()  # 不抛即通过


@pytest.mark.asyncio
async def test_stop_cancels_heartbeat_and_disconnects():
    consumer, _, ws = make_consumer()
    await consumer.start()
    await asyncio.sleep(0)

    await consumer.stop()

    assert ws.disconnected is True
    assert consumer._ping_task is None


@pytest.mark.asyncio
async def test_stop_tolerates_disconnect_failure():
    """关停路径上的异常只记日志——否则一次失败的断连会卡住整个 shutdown。"""
    class BadWs(FakeWsClient):
        async def _disconnect(self) -> None:
            raise RuntimeError("断开失败")

    consumer, _, _ = make_consumer(ws=BadWs())
    await consumer.start()

    await consumer.stop()  # 不抛即通过


# --------------------------------------------------------------------------- #
# 环境变量装配
# --------------------------------------------------------------------------- #
def test_disabled_by_default(monkeypatch):
    """默认 false：没配凭据时不该自动去连。"""
    monkeypatch.delenv("FEISHU_ENABLED", raising=False)

    assert feishu_enabled() is False
    assert build_consumer_from_env(TaskExecutor(lambda t, o: None), None) is None


@pytest.mark.parametrize("value,expected", [
    ("true", True), ("TRUE", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), ("0", False), ("no", False), ("", False), ("鬼画符", False),
])
def test_enabled_flag_parsing(monkeypatch, value, expected):
    monkeypatch.setenv("FEISHU_ENABLED", value)

    assert feishu_enabled() is expected


def test_build_from_env_reads_config(monkeypatch):
    monkeypatch.setenv("FEISHU_ENABLED", "true")
    monkeypatch.setenv("FEISHU_APP_ID", "cli_from_env")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret_from_env")
    monkeypatch.setenv("FEISHU_DOMAIN", "https://open.larksuite.com")
    monkeypatch.setenv("FEISHU_SESSION_SCOPE", "chat")

    consumer = build_consumer_from_env(
        TaskExecutor(lambda t, o: None),
        DatabaseRouter("sqlite:///:memory:").channel_sessions,
    )

    assert consumer is not None
    assert consumer._app_id == "cli_from_env"
    assert consumer._domain == "https://open.larksuite.com"
    assert consumer._session_scope == "chat"


def test_unrecognized_scope_falls_back(monkeypatch):
    """作用域拼错不该让 Channel 起不来——归一到默认仍是可用行为。"""
    monkeypatch.setenv("FEISHU_ENABLED", "true")
    monkeypatch.setenv("FEISHU_APP_ID", "cli_x")
    monkeypatch.setenv("FEISHU_APP_SECRET", "s")
    monkeypatch.setenv("FEISHU_SESSION_SCOPE", "thread")

    consumer = build_consumer_from_env(
        TaskExecutor(lambda t, o: None),
        DatabaseRouter("sqlite:///:memory:").channel_sessions,
    )

    assert consumer._session_scope == "reply"


# --------------------------------------------------------------------------- #
# 端到端接线：事件进来 → 任务出去
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_event_flows_through_to_executor():
    """把 gateway 从 consumer 里取出来喂一个事件，验证整条接线通。"""
    import json

    executor = RecordingExecutor()
    consumer, api, _ = make_consumer(executor=executor)
    await consumer.start()

    event = SimpleNamespace(
        header=SimpleNamespace(event_id="evt-1"),
        event=SimpleNamespace(
            sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou_sender")),
            message=SimpleNamespace(
                message_id="om_1", chat_id="oc_1", chat_type="group",
                message_type="text", content=json.dumps({"text": "@_user_1 你好"}),
                root_id=None, parent_id=None, thread_id=None,
                mentions=[SimpleNamespace(key="@_user_1",
                                          id=SimpleNamespace(open_id="ou_bot"))],
            ),
        ),
    )
    consumer.gateway.handle_event(event)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(executor.tasks) == 1
    assert executor.tasks[0].user_input == "你好"
    assert executor.tasks[0].user_id == "ou_sender"
    assert api.replies  # ack 已发出
    await consumer.stop()
