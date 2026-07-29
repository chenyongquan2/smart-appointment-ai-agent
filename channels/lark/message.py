"""飞书消息的领域模型（change: feishu-channel-integration）。

把 lark-oapi 的 SDK 事件对象收敛成一个小 dataclass，让下游（会话键解析、gateway 判定）
只依赖这几个字段，而不依赖 SDK 类型——换 IM 平台时替换的是「怎么填这个 dataclass」，
下游逻辑不动。这也让单测能直接构造消息，不必伪造 SDK 对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class IncomingMessage:
    """一条收到的飞书消息（只保留下游真正用到的字段）。

    Attributes:
        event_id: 事件 id，用于去重（防重复消费导致重复下单）。
        message_id: 本条消息 id。
        chat_id: 群 id。
        chat_type: ``group`` / ``p2p``。
        text: 已剥离 @ 占位符的正文。
        sender_open_id: 发送者 open_id → 作 ``user_id``，使长期偏好按人隔离。
        root_id: 回复链根消息 id；**首条消息没有这个字段**。
        parent_id: 直接父消息 id；同样只在回复上出现。
        thread_id: 话题 id。**刻意保留但不参与会话键**——实测它只出现在续话消息上，
            首条没有，排进解析链首位会让首条与其回复落到不同会话。留着仅供排障日志。
        mentioned_open_ids: 本条消息 @ 到的所有 open_id，用于判定是否 @ 了自己。
    """

    event_id: str
    message_id: str
    chat_id: str
    chat_type: str
    text: str
    sender_open_id: Optional[str] = None
    root_id: Optional[str] = None
    parent_id: Optional[str] = None
    thread_id: Optional[str] = None
    mentioned_open_ids: Tuple[str, ...] = field(default_factory=tuple)

    def mentions(self, open_id: str) -> bool:
        """本条消息是否 @ 了给定 open_id。

        判定必须基于 open_id：``mentioned_type == "bot"`` 会把群里**其它**机器人也算进来，
        按 ``name`` 匹配则一改名就失效。
        """
        return open_id in self.mentioned_open_ids
