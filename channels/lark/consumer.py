"""长连接消费者：订阅 `im.message.receive_v1` 并接入 FastAPI 生命周期（tasks 3.6）。

## 为什么不能直接用 SDK 的 `start()`

`lark_oapi.ws.client` 有两处与「跑在别人的事件循环里」冲突的设计，都必须绕开：

1. **`start()` 自己 run 一个循环**：内部是 ``loop.run_until_complete(self._connect())``
   + ``loop.run_until_complete(_select())``。FastAPI lifespan 里已有运行中的循环，
   调它会抛 "loop is already running"。故本模块改为 ``await client._connect()``，
   并自行起 ``_ping_loop()`` 的 task。

2. **模块级 `loop` 是 import 时抓的**（``loop = asyncio.get_event_loop()``，见该模块
   第 32 行），而 ``_connect()`` 用 ``loop.create_task(self._receive_message_loop())``
   起收包循环、``_receive_message_loop()`` 又用 ``loop.create_task(self._handle_message(msg))``
   处理每条消息。在 FastAPI 下，模块 import 早于 uvicorn 建循环，那个 ``loop``
   **不是**运行中的循环——于是收包 task 永远不会被执行：**连接显示成功，却一条事件都收
   不到，且不报任何错**。这是最难查的一类故障，故 ``start()`` 前必须把该模块全局指向
   当前运行的循环（``_bind_sdk_loop``）。

两条都是读 SDK 源码才发现的，看文档看不出来。

## 失败不拖垮主服务

飞书接入是可选能力（``FEISHU_ENABLED``）。凭据错、权限缺、网络不通时，本模块记结构化
错误日志并返回 ``False``，**不抛异常**——一个 Channel 不可用不该让 Web 端也起不来。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Optional

import lark_oapi as lark

from channels.lark.client import LarkClient, describe_bot
from channels.lark.delivery import LarkDelivery
from channels.lark.gateway import LarkGateway
from channels.lark.session_key import SCOPE_REPLY, normalize_scope
from executor import TaskExecutor

logger = logging.getLogger(__name__)


def _bind_sdk_loop() -> None:
    """把 lark-oapi ws 模块的全局 ``loop`` 指向当前运行的事件循环。

    见模块 docstring 第 2 点：不做这件事，收包 task 会被投到一个不运行的循环上，
    表现为「连上了但永远收不到事件」且无任何报错。
    """
    import lark_oapi.ws.client as ws_module

    running = asyncio.get_running_loop()
    if getattr(ws_module, "loop", None) is not running:
        logger.info("已将 lark-oapi 的事件循环重绑定到当前运行循环")
        ws_module.loop = running


class LarkConsumer:
    """飞书长连接消费者。

    Args:
        app_id / app_secret: 应用凭据。
        domain: 接入域名（飞书 / Lark 可配）。
        executor: 任务执行层。
        channel_sessions: 渠道会话映射仓库。
        session_scope: 会话作用域（``reply`` / ``chat``）。
        client: 覆盖 API 客户端（测试注入 fake）。
        ws_client_factory: 覆盖 ws 客户端构造（测试注入 fake，避免真连）。
            签名为 ``(event_handler) -> ws_client``。
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        executor: TaskExecutor,
        channel_sessions: Any,
        domain: str = lark.FEISHU_DOMAIN,
        session_scope: str = SCOPE_REPLY,
        client: Optional[Any] = None,
        ws_client_factory: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._domain = domain
        self._executor = executor
        self._channel_sessions = channel_sessions
        self._session_scope = normalize_scope(session_scope)
        self._client = client or LarkClient(app_id, app_secret, domain)
        self._ws_factory = ws_client_factory or self._default_ws_factory
        self._ws: Optional[Any] = None
        self._ping_task: Optional[asyncio.Task] = None
        self.gateway: Optional[LarkGateway] = None

    def _default_ws_factory(self, event_handler: Any) -> Any:
        return lark.ws.Client(
            self._app_id, self._app_secret,
            event_handler=event_handler,
            domain=self._domain,
            log_level=lark.LogLevel.INFO,
        )

    async def start(self) -> bool:
        """启动自检 → 装配 gateway/delivery → 建连 → 起心跳。

        Returns:
            是否成功启动。失败只记日志、返回 ``False``，不抛异常。
        """
        if not self._app_id or not self._app_secret:
            logger.error("飞书凭据缺失，接入未启动（见 docs/feishu-app-setup.md）")
            return False

        # ① 启动自检：顺带拿到自身 open_id 供 @ 判定。取不到不立即放弃——继续建连，
        #    由 _connect 给出更权威的失败原因（凭据错时它也会失败）。
        bot = await self._client.fetch_bot_info()
        if bot is None:
            logger.error(
                "启动自检失败：取不到机器人信息。请依次核对——应用是否已启用「机器人」能力、"
                "权限是否已勾选、版本是否已发布通过审核、app_id/app_secret 是否正确"
                "（见 docs/feishu-app-setup.md）"
            )
        else:
            logger.info("飞书机器人自检通过：%s", describe_bot(bot))

        bot_open_id = (bot or {}).get("open_id")

        # ② 装配：delivery 是终态唯一出口，gateway 是收件入口，两者都用同一个 client 投递。
        delivery = LarkDelivery(self._client)
        self.gateway = LarkGateway(
            executor=self._executor,
            sender=self._client,
            channel_sessions=self._channel_sessions,
            bot_open_id=bot_open_id,
            on_complete=delivery,
            session_scope=self._session_scope,
        )

        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self.gateway.handle_event)
            .build()
        )
        self._ws = self._ws_factory(handler)

        # ③ ★ 必须在建连之前重绑循环，否则收包 task 进了不运行的循环（见模块 docstring）。
        _bind_sdk_loop()

        try:
            await self._ws._connect()
        except Exception:  # noqa: BLE001 —— Channel 起不来不该让主服务也起不来
            logger.exception("飞书长连接建立失败，接入未启动")
            return False

        # ④ 心跳：SDK 的 start() 会起它，我们绕开了 start() 就得自己起。
        self._ping_task = asyncio.create_task(
            self._ws._ping_loop(), name="lark-ping-loop"
        )
        logger.info(
            "飞书接入已启动",
            extra={"domain": self._domain, "session_scope": self._session_scope},
        )
        return True

    async def stop(self) -> None:
        """停止心跳并断开连接；每一步都独立容错，确保后续步骤照常执行。"""
        if self._ping_task is not None:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._ping_task = None

        if self._ws is not None:
            try:
                await self._ws._disconnect()
            except Exception:  # noqa: BLE001 —— 关停路径上的异常只记日志
                logger.warning("断开飞书长连接时出错", exc_info=True)
            self._ws = None

        logger.info("飞书接入已停止")


def feishu_enabled() -> bool:
    """``FEISHU_ENABLED`` 是否为真。默认 **false**——没配凭据时不该自动去连。"""
    return os.getenv("FEISHU_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


def build_consumer_from_env(
    executor: TaskExecutor,
    channel_sessions: Any,
) -> Optional[LarkConsumer]:
    """按环境变量装配 consumer；未启用时返回 ``None``。

    由组合根（``app.py``）调用。凭据只从 ``.env`` 读，绝不进 LLM 上下文。
    """
    if not feishu_enabled():
        logger.info("FEISHU_ENABLED 未开启，跳过飞书接入")
        return None

    return LarkConsumer(
        app_id=os.getenv("FEISHU_APP_ID", ""),
        app_secret=os.getenv("FEISHU_APP_SECRET", ""),
        domain=os.getenv("FEISHU_DOMAIN", lark.FEISHU_DOMAIN),
        session_scope=os.getenv("FEISHU_SESSION_SCOPE", SCOPE_REPLY),
        executor=executor,
        channel_sessions=channel_sessions,
    )
