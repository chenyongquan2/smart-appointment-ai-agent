"""SDK 事件 → ``IncomingMessage``（change: feishu-channel-integration，tasks 3.4）。

这是唯一接触 lark-oapi 事件对象形状的地方。下游（会话键解析、gateway 判定）只认
``IncomingMessage``，故换 IM 平台时替换的是本文件，其余逻辑不动。

字段取法依据真实租户实测（``docs/evidence/feishu-event-payload-2026-07-29.log``）：
- ``root_id`` / ``parent_id`` / ``thread_id`` **只在回复消息上出现**，首条 @bot 消息没有
- ``sender.sender_id.user_id`` 在未开通通讯录权限时**不下发**，故只取 ``open_id``
- 正文在 ``message.content`` 里是 JSON 字符串，形如 ``{"text":"@_user_1 你好"}``，
  其中 ``@_user_1`` 是 @ 占位符，需按 ``mentions[].key`` 剔除
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from channels.lark.message import IncomingMessage

logger = logging.getLogger(__name__)


def _dig(obj: Any, path: str) -> Any:
    """按 ``a.b.c`` 逐级取属性；任一级缺失或为 None 即返回 None。"""
    cur = obj
    for part in path.split("."):
        cur = getattr(cur, part, None)
        if cur is None:
            return None
    return cur


def _extract_text(content: Optional[str], mention_keys: tuple[str, ...]) -> str:
    """从 ``content`` 的 JSON 里取正文，并剔除 @ 占位符。

    占位符按 ``mentions[].key``（形如 ``@_user_1``）精确剔除，而不是用正则猜 ``@\\S+``——
    后者会把用户正文里真实的 "@" 内容也吃掉。
    """
    if not content:
        return ""
    try:
        text = json.loads(content).get("text", "") or ""
    except (json.JSONDecodeError, AttributeError):
        # 非预期的 content 形态：不抛异常（一条畸形消息不该拖垮收包循环），回空串由上层忽略。
        logger.warning("消息 content 解析失败，按空正文处理", extra={"content": content[:200]})
        return ""

    for key in mention_keys:
        text = text.replace(key, "")
    # 剔除占位符后会留下多余空格，折叠为单空格并去首尾。
    return " ".join(text.split())


def parse_message_event(data: Any) -> Optional[IncomingMessage]:
    """把一个 ``im.message.receive_v1`` 事件解析为 ``IncomingMessage``。

    Returns:
        解析结果；缺少 event_id / message_id / chat_id 这类必需字段时返回 ``None``
        （畸形事件，只记日志、不处理）。**不因 message_type 非文本而返回 None**——
        那种消息仍要回一句提示，判定交给 gateway。
    """
    header = getattr(data, "header", None)
    event = getattr(data, "event", None)
    message = getattr(event, "message", None)

    event_id = getattr(header, "event_id", None)
    message_id = getattr(message, "message_id", None)
    chat_id = getattr(message, "chat_id", None)
    if not event_id or not message_id or not chat_id:
        logger.warning(
            "事件缺少必需字段，已忽略",
            extra={"event_id": event_id, "message_id": message_id, "chat_id": chat_id},
        )
        return None

    mentions = getattr(message, "mentions", None) or []
    mention_keys = tuple(
        k for k in (getattr(m, "key", None) for m in mentions) if k
    )
    mentioned_open_ids = tuple(
        oid for oid in (_dig(m, "id.open_id") for m in mentions) if oid
    )

    return IncomingMessage(
        event_id=event_id,
        message_id=message_id,
        chat_id=chat_id,
        chat_type=getattr(message, "chat_type", "") or "",
        message_type=getattr(message, "message_type", "") or "",
        text=_extract_text(getattr(message, "content", None), mention_keys),
        sender_open_id=_dig(event, "sender.sender_id.open_id"),
        root_id=getattr(message, "root_id", None),
        parent_id=getattr(message, "parent_id", None),
        thread_id=getattr(message, "thread_id", None),
        mentioned_open_ids=mentioned_open_ids,
    )
