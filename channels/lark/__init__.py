"""飞书 / Lark 渠道（change: feishu-channel-integration）。

飞书与 Lark 是同一套 API（``open.feishu.cn`` / ``open.larksuite.com``），域名可配，
同一份代码可跑两个实例。
"""

from channels.lark.message import IncomingMessage
from channels.lark.session_key import (
    CHANNEL,
    SCOPE_CHAT,
    SCOPE_REPLY,
    SessionKey,
    normalize_scope,
    resolve_session_key,
)

__all__ = [
    "IncomingMessage",
    "SessionKey",
    "resolve_session_key",
    "normalize_scope",
    "CHANNEL",
    "SCOPE_REPLY",
    "SCOPE_CHAT",
]
