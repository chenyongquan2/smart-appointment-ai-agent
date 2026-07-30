"""飞书 API 客户端薄封装（change: feishu-channel-integration，tasks 3.5）。

只暴露本期真正需要的两件事：取自身 open_id（供 @ 判定）、按消息 id 回复文本（ack 与结果
投递）。其余 SDK 能力一概不包装——需要时再加，避免长出一个"什么都能干"的上帝对象。

用 SDK 的异步方法（``areply`` / ``arequest``）而非同步版本，因为调用点在事件循环里：
gateway 的 ack 与 delivery 的结果投递都是 ``create_task`` 出来的协程，同步 HTTP 会把
整个事件循环连同长连接的收包一起卡住。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import lark_oapi as lark
from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody
from lark_oapi.core.enum import AccessTokenType, HttpMethod
from lark_oapi.core.model import BaseRequest

from channels.lark.format import build_text_card

logger = logging.getLogger(__name__)

# 取自身信息的接口，SDK 未包装，走原始请求。实测返回 bot.open_id 与事件载荷里
# mentions[].id.open_id 完全一致（见 docs/evidence/feishu-event-payload-2026-07-29.log）。
_BOT_INFO_URI = "/open-apis/bot/v3/info"

_ACTIVATED = 2  # bot.activate_status 的「已启用」取值


class LarkClient:
    """飞书 API 客户端。

    Args:
        app_id / app_secret: 应用凭据（来自 ``.env``，绝不进 LLM 上下文）。
        domain: 国内飞书 ``https://open.feishu.cn``；国际版 Lark ``https://open.larksuite.com``。
    """

    def __init__(self, app_id: str, app_secret: str, domain: str = lark.FEISHU_DOMAIN) -> None:
        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .domain(domain)
            .build()
        )

    async def fetch_bot_info(self) -> Optional[dict[str, Any]]:
        """取机器人自身信息（``open_id`` / ``app_name`` / ``activate_status``）。

        Returns:
            成功时返回 ``bot`` 字段的字典；失败返回 ``None`` 并记结构化错误日志。
            **不抛异常**：调用方（consumer 启动自检）要能区分「取不到」与「崩了」，
            取不到时 gateway 仍可走 @ 判定的退化路径。
        """
        request = (
            BaseRequest.builder()
            .http_method(HttpMethod.GET)
            .uri(_BOT_INFO_URI)
            .token_types({AccessTokenType.TENANT})
            .build()
        )
        try:
            response = await self._client.arequest(request)
        except Exception:  # noqa: BLE001 —— 网络/凭据异常都收口成 None
            logger.exception("取机器人信息失败（请求异常）")
            return None

        if not response.success():
            logger.error(
                "取机器人信息失败",
                extra={"code": response.code, "msg": response.msg},
            )
            return None

        try:
            body = json.loads(response.raw.content.decode())
        except Exception:  # noqa: BLE001
            logger.exception("机器人信息响应解析失败")
            return None
        return body.get("bot") or None

    async def reply(
        self,
        message_id: str,
        text: str,
        *,
        in_thread: bool = True,
        rich: bool = False,
    ) -> bool:
        """回复指定消息。

        用**回复**而非往群里发新消息，有两个不可让的理由：① 结果出现在触发它的那条消息
        下方，群里多人并行提问时不会错位；② 会话键靠回复链/话题维系，bot 的消息挂进链里，
        用户接着说时才仍收敛到同一会话（见 ``session_key`` 模块 docstring）。

        Args:
            message_id: 被回复的消息 id。
            text: 正文（markdown 由 ``rich`` 决定是否渲染）。
            in_thread: ``True``（默认）发进**话题**——原消息成为话题根，一问一答连同后续
                追问都收进同一话题，主聊天流只留一条折叠入口。``False`` 则是引用回复，
                每条消息头上都顶一遍被引用的原文，消息一多群里就糊。
            rich: ``True`` 时用交互式卡片渲染 markdown（加粗/换行），否则纯文本原样发出。

        Returns:
            是否投递成功。失败只返回 ``False`` 并记日志——重试策略归 delivery，
            本层不做重试（否则两处都重试会放大成 N×M 次）。
        """
        if rich:
            msg_type = "interactive"
            payload: Any = build_text_card(text)
        else:
            msg_type = "text"
            payload = {"text": text}

        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                # ensure_ascii=False：否则中文被转成 \uXXXX，虽能显示但日志里没法读。
                .content(json.dumps(payload, ensure_ascii=False))
                .msg_type(msg_type)
                .reply_in_thread(in_thread)
                .build()
            )
            .build()
        )
        try:
            response = await self._client.im.v1.message.areply(request)
        except Exception:  # noqa: BLE001
            logger.exception("投递消息失败（请求异常）", extra={"message_id": message_id})
            return False

        if not response.success():
            logger.error(
                "投递消息失败",
                extra={"message_id": message_id, "code": response.code, "msg": response.msg},
            )
            return False
        return True


def describe_bot(bot: Optional[dict[str, Any]]) -> str:
    """把机器人信息渲染成一行启动日志；顺带把「未启用」显式点出来。"""
    if not bot:
        return "机器人信息不可用"
    status = bot.get("activate_status")
    # 刻意只用中文与 ASCII，不加 emoji/符号装饰：这行要进日志，而 Windows 控制台默认
    # gbk 编码，非 ASCII 装饰符（如 ⚠）会让 logging 在运行时抛 UnicodeEncodeError。
    flag = "已启用" if status == _ACTIVATED else f"未启用(activate_status={status})"
    return f"{bot.get('app_name')} open_id={bot.get('open_id')} {flag}"
