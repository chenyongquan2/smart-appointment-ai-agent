"""飞书事件入口：收件 → 判定 → 提交任务 → 秒回 ack（tasks 3.4）。

**本模块的每一行都受一个硬约束支配：SDK 是同步调用本回调的，且协议 ack 在回调返回之后
才写回。** 见 `lark_oapi.ws.client.Client._handle_data_frame`——它在协程里直接
``self._event_handler._do_without_validation(pl)``，然后才 ``await self._write_message(...)``。

于是：

- 回调运行在事件循环里 → ``executor.submit()``（内部 ``create_task``）可用；
- 回调是**同步代码跑在事件循环上**，阻塞多久整个循环就停多久——不只是本条消息的协议
  ack 被延后，同一时刻所有协程（含收包）都被冻住。故回调里 MUST NOT 做网络 I/O：
  发"处理中"提示必须 ``create_task`` 异步发，绝不能同步等它返回。

  （精确一点：SDK 的 ``_receive_message_loop`` 给每条消息各起一个 task，所以收包循环
  本身不会被某条消息的处理"排队"拖住；真正的问题是同步阻塞会占住整个事件循环。结论
  相同，但别误以为"只影响这一条消息"。）

双层 ack 因此是两件不同的事，文档里也刻意分开写：
1. **协议 ack**：本回调尽快返回，由 SDK 写回帧；
2. **用户可见 ack**：另起 task 用 **reply** 发一条"处理中"。

用 reply 而非表情回应不是审美选择——``reply`` 作用域的会话键靠回复链维系，bot 的 ack
挂进链里之后，用户回复 ack 时 ``root_id`` 仍指向最初那条消息，会话才不会断（见
``session_key`` 模块 docstring）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional, Protocol

from channels.lark.dedup import TTLDedup
from channels.lark.parser import parse_message_event
from channels.lark.session_key import CHANNEL, SCOPE_REPLY, resolve_session_key
from executor import Task, TaskExecutor, TaskResult

logger = logging.getLogger(__name__)

ACK_REPLY = "收到，正在处理…"
UNSUPPORTED_REPLY = "我目前只看得懂文字消息，麻烦用文字描述一下。"
EMPTY_REPLY = "你 @ 了我但没说事儿——想问什么？"


class MessageSender(Protocol):
    """gateway 对投递能力的最小依赖（真实实现见 ``client.py``，测试注入 fake）。"""

    async def reply(
        self, message_id: str, text: str, *, in_thread: bool = True, rich: bool = False,
    ) -> bool:
        ...


class LarkGateway:
    """飞书消息事件的处理入口。

    Args:
        executor: 任务执行层。
        sender: 消息投递能力。
        channel_sessions: 渠道会话映射仓库（``DatabaseRouter.channel_sessions``）。
        bot_open_id: 机器人自身 open_id，用于 @ 判定。``None`` 时退化为「@ 到任意机器人
            即认为是我」并告警——飞书按权限只下发 @ 到本 bot 的群消息，故该退化是安全的，
            但群里出现第二个机器人时就可能误抢答。
        on_complete: 任务终态回调（delivery）。
        session_scope: 会话作用域（``reply`` / ``chat``）。
        dedup: 事件去重器；缺省新建一个默认配置的。
    """

    def __init__(
        self,
        executor: TaskExecutor,
        sender: MessageSender,
        channel_sessions: Any,
        bot_open_id: Optional[str],
        on_complete: Callable[[TaskResult], Any],
        session_scope: str = SCOPE_REPLY,
        dedup: Optional[TTLDedup] = None,
    ) -> None:
        self._executor = executor
        self._sender = sender
        self._channel_sessions = channel_sessions
        self._bot_open_id = bot_open_id
        self._on_complete = on_complete
        self._session_scope = session_scope
        self._dedup = dedup or TTLDedup()
        # 持有在途的 ack task 强引用，防被事件循环提前回收。
        self._pending: set[asyncio.Task] = set()

        if not bot_open_id:
            logger.warning(
                "未提供机器人 open_id，@ 判定退化为「@ 到任意机器人即视为我」；"
                "群内若有第二个机器人可能误响应"
            )

    # ── SDK 事件回调（同步、必须尽快返回）────────────────────────────────────
    def handle_event(self, data: Any) -> None:
        """处理一个 `im.message.receive_v1` 事件。

        整个函数体只做内存计算 + 两次 ``create_task``，唯一的 I/O 是映射表的本地 SQLite
        写（亚毫秒级）。任何异常都在此收口——异常冒回 SDK 会让它把整帧标记为处理失败。
        """
        try:
            self._handle(data)
        except Exception:  # noqa: BLE001 —— 一条畸形消息不该拖垮收包循环
            logger.exception("处理飞书事件失败")

    def _handle(self, data: Any) -> None:
        message = parse_message_event(data)
        if message is None:
            return  # 畸形事件，parser 已记日志

        # ① 去重先于一切：重复投递意味着重复下单（create_appointment 无幂等键）。
        if not self._dedup.is_new(message.event_id):
            logger.info("重复事件，已忽略", extra={"event_id": message.event_id})
            return

        # ② @ 判定：按 open_id 比对，不看 mentioned_type（群内其它机器人会误判）、
        #    不看 name（改名即失效）。
        if not self._is_for_me(message):
            return  # 不是叫我，静默忽略（这是 spec 明确要求的静默，与「绝不静默」不冲突）

        # ③ 非文本 / 空正文：仍要回一句——用户 @ 了机器人却毫无反应，观感等同于坏了。
        if message.message_type != "text":
            self._spawn(self._sender.reply(message.message_id, UNSUPPORTED_REPLY))
            return
        if not message.text:
            self._spawn(self._sender.reply(message.message_id, EMPTY_REPLY))
            return

        # ④ 会话键 → 绑定。bind 幂等且已存在不覆盖，故同一条回复链恒定落到同一会话。
        key = resolve_session_key(message, self._session_scope)
        session_id = self._channel_sessions.bind(
            CHANNEL, key.scope, key.external_id, key.session_id
        )

        # ⑤ 用户可见 ack：异步发，绝不在此等它返回（会卡住收包循环与协议 ack）。
        ack_task = self._spawn(self._sender.reply(message.message_id, ACK_REPLY))

        # ⑥ 提交任务。ack_task 放进 metadata：delivery 在投结果前 await 它，
        #    使「ack 先于结果」成为确定性保证而不是靠"ack 比 Agent 快"的侥幸。
        self._executor.submit(
            Task(
                session_id=session_id,
                user_input=message.text,
                user_id=message.sender_open_id,  # 长期偏好按人隔离
                channel=CHANNEL,
                metadata={
                    "message_id": message.message_id,
                    "chat_id": message.chat_id,
                    "event_id": message.event_id,
                    "ack_task": ack_task,
                },
            ),
            self._on_complete,
        )
        # 日志里带齐**所有**会话键候选字段（不只是被选中的那个）：会话键的定义已经因为
        # 实测被改过一次，日后若话题模式下字段又变，排障时要能一眼看出"当时飞书下发了什么"，
        # 而不是再去搭一遍探针。
        logger.info(
            "已提交任务",
            extra={"session_id": session_id, "event_id": message.event_id,
                   "scope": key.scope, "external_id": key.external_id,
                   "thread_id": message.thread_id, "root_id": message.root_id,
                   "parent_id": message.parent_id, "message_id": message.message_id},
        )

    # ── 内部 ────────────────────────────────────────────────────────────────
    def _is_for_me(self, message: Any) -> bool:
        if self._bot_open_id:
            return message.mentions(self._bot_open_id)
        # 退化路径：飞书按 im:message.group_at_msg 权限只下发 @ 到本 bot 的群消息，
        # 故"有任何 @ 就认作我"在单机器人群里等价，多机器人群里才会出偏差。
        return bool(message.mentioned_open_ids)

    def _spawn(self, coro: Awaitable[Any]) -> asyncio.Task:
        """把一个协程丢进事件循环并持有强引用（否则可能被提前回收）。"""
        task = asyncio.ensure_future(coro)
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return task
