"""会话键解析：把一条飞书消息映射到 Agent 的 ``session_id``（tasks 3.3）。

**这个模块的解析顺序是实测校正过的，改动前请先读完下面这段。**

真实租户实测（2026-07-29，普通群；原始载荷见
``docs/evidence/feishu-event-payload-2026-07-29.log``）：

    首条 @bot 消息 ── thread_id 无 / root_id 无 / message_id 有
    对消息的回复  ── thread_id 有 / root_id 有 / message_id 有

于是 ``thread_id`` **只出现在续话消息上、首条没有**。原设计把解析链定为
``thread_id → root_id → message_id``，代入实测就是：首条落到 ``feishu:{message_id}``、
它的回复落到 ``feishu:{thread_id}``——两者不同，多轮直接断裂。把 ``thread_id`` 排在首位
等于亲手切断自己要建立的那条链。

正确的链是 ``root_id → message_id``，它天然自洽：首条取自身 ``message_id``；其后每条
回复的 ``root_id`` 都指回那条首条消息，全部收敛到同一会话。

配套约束：``reply`` 作用域依赖回复链，所以「用户可见 ack 必须用 reply 发送」不是体验
偏好而是硬需求——bot 的 ack 挂进同一条链后，用户回复 ack 时 ``root_id`` 仍指向最初那条
消息，会话不变。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from channels.lark.message import IncomingMessage

CHANNEL = "feishu"

# 会话作用域。
SCOPE_REPLY = "reply"  # 默认：一次 @bot 开一条会话，在该消息下回复即继续同一会话
SCOPE_CHAT = "chat"    # 整群共用一条会话
_SCOPES = (SCOPE_REPLY, SCOPE_CHAT)

# 真话题群（首条消息即带 thread_id）的专用作用域**刻意未实现**：目前没有可验证的话题群，
# 加一个未经实测的模式比不加更糟——本模块的解析顺序被定反过一次，教训就来自"未实测的假设"。


@dataclass(frozen=True)
class SessionKey:
    """解析结果。

    Attributes:
        scope: 生效的作用域。
        external_id: 解析出的会话键（落 DB 的就是这个值，不是原始事件字段）。
        session_id: 派生出的候选 Agent 会话标识。
    """

    scope: str
    external_id: str
    session_id: str


def normalize_scope(scope: Optional[str]) -> str:
    """把配置值归一为受支持的作用域；无法识别时退回默认并不报错。

    宽容处理是刻意的：作用域来自环境变量，拼错一个字母不该让整个 Channel 起不来——
    退回默认 ``reply`` 仍是可用行为，而调用方会在日志里看到归一结果。
    """
    if scope is None:
        return SCOPE_REPLY
    value = scope.strip().lower()
    return value if value in _SCOPES else SCOPE_REPLY


def resolve_session_key(message: IncomingMessage, scope: str = SCOPE_REPLY) -> SessionKey:
    """解析一条消息所属的会话键。

    Args:
        message: 收到的消息。
        scope: 会话作用域（``reply`` 默认 / ``chat``）；非法值按 ``normalize_scope`` 归一。

    Returns:
        ``SessionKey``；``session_id`` 形如 ``feishu:{external_id}``。
    """
    effective = normalize_scope(scope)

    if effective == SCOPE_CHAT:
        external_id = message.chat_id
    else:
        # ★ root_id → message_id。注意 thread_id 不在链里（见模块 docstring）。
        #   首条消息没有 root_id，取自身 message_id 开一条新会话；
        #   其后每条回复的 root_id 都指回那条首条消息，于是收敛到同一会话。
        external_id = message.root_id or message.message_id

    return SessionKey(
        scope=effective,
        external_id=external_id,
        session_id=f"{CHANNEL}:{external_id}",
    )
