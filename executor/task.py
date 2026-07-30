"""任务模型：Channel 与 Agent 之间传递的输入与终态（change: feishu-channel-integration）。

Channel 层只读这里的结构化字段，**不解析** Agent 的 ``[REPLY]`` / ``[THOUGHT]`` 输出协议
——协议解析归 executor 承担，这样「换掉飞书换成钉钉，Agent 层零改动」的分层判据才成立。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TaskStatus(str, Enum):
    """任务终态。

    五种终态**都必须**被投递给用户（绝不静默），文案由 Channel 的 delivery 决定。
    """

    SUCCEEDED = "succeeded"                      # Agent 正常给出回复
    FAILED = "failed"                            # 执行抛异常，或被护栏拦停（打转/预算/重试耗尽/跑满步数）
    TIMEOUT = "timeout"                          # 触达任务墙钟总超时，已被中断
    GUARDRAIL_EXHAUSTED = "guardrail_exhausted"  # LLM 重试护栏耗尽（FAILED 的一个可分辨子类）
    BUSY = "busy"                                # 该会话排队已满，未入队执行


@dataclass(frozen=True)
class Task:
    """一次待执行的 Agent 任务。

    Attributes:
        session_id: 会话标识；executor 据此做「同话题串行」。
        user_input: 本轮用户输入。
        user_id: 提交者标识，用于长期偏好按人隔离（群聊场景必须传，否则全群偏好混作
            一个 ``default_user``）。``None`` 时沿用编排层的默认用户，Web 行为不变。
        channel: 来源渠道（``web`` / ``feishu`` …），仅作日志与排障标注。
        metadata: 渠道自带的回投上下文（如飞书的 message_id / chat_id）；executor 不解读，
            原样带回给 delivery。
    """

    session_id: str
    user_input: str
    user_id: Optional[str] = None
    channel: str = "web"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskResult:
    """任务终态结果。

    Attributes:
        status: 终态枚举。
        reply_text: 要投递给用户的文本。**五种终态都非空**——即使失败/超时也带一句可读
            说明，这是「绝不静默」的落点。
        error: 供排障的技术细节（异常摘要等）；不面向用户。
        task: 触发本结果的原任务，供 delivery 取回投上下文。
    """

    status: TaskStatus
    reply_text: str
    error: Optional[str] = None
    task: Optional[Task] = None

    @property
    def succeeded(self) -> bool:
        return self.status is TaskStatus.SUCCEEDED
