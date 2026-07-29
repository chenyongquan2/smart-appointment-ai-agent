"""终态投递：把任务结果送回原会话（change: feishu-channel-integration，tasks 3.5）。

**唯一出口原则**：executor 的五种终态（成功 / 失败 / 超时 / guardrail 耗尽 / 忙碌拒绝）
全部经本模块投递，没有第二条路。「绝不静默」这条要求之所以能成立，就是因为这里没有
任何一条分支会「什么都不做」——用户可感知的流程 MUST NOT 无声结束。

Channel 不解析 Agent 的输出协议：``TaskResult.reply_text`` 已由 executor 从 token 流里
择出并对五种终态都填好，本模块只负责「送」和「送不出去怎么办」。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional, Protocol

from executor import TaskResult, TaskStatus

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 2      # 首次之外再试 2 次，共 3 次
DEFAULT_RETRY_DELAY = 1.0    # 重试间隔基准秒数（线性退避，投递不是重活儿）

# reply_text 意外为空时的兜底。绝不投空串——那既是静默，飞书也会拒收空内容。
_EMPTY_FALLBACK = "处理完成了，但没有生成可展示的回复。麻烦换个说法再问一次。"


class MessageSender(Protocol):
    """delivery 对投递能力的最小依赖（真实实现见 ``client.LarkClient``）。"""

    async def reply_text(self, message_id: str, text: str) -> bool:
        ...


class LarkDelivery:
    """任务终态的统一投递出口。

    Args:
        sender: 消息投递能力。
        max_retries: 首次失败后的重试次数。
        sleep: 退避实现（测试注入 no-op，不真等）。
    """

    def __init__(
        self,
        sender: MessageSender,
        max_retries: int = DEFAULT_MAX_RETRIES,
        sleep: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> None:
        self._sender = sender
        self._max_retries = max_retries
        self._sleep = sleep or asyncio.sleep

    async def __call__(self, result: TaskResult) -> None:
        """executor 的终态回调。异常在此收口——delivery 崩了不该把 worker 带走。"""
        try:
            await self._deliver(result)
        except Exception:  # noqa: BLE001
            logger.exception(
                "终态投递出现未预期异常",
                extra={"status": getattr(result, "status", None)},
            )

    async def _deliver(self, result: TaskResult) -> None:
        metadata = (result.task.metadata if result.task else {}) or {}
        message_id = metadata.get("message_id")
        if not message_id:
            # 没有回投目标就真没法投了——但必须留下可排查的记录，不能悄悄咽下。
            logger.error(
                "终态无回投目标，无法投递",
                extra={"status": result.status.value, "error": result.error},
            )
            return

        # ① 先等 ack 落地，让「ack 先于结果」成为确定性保证，而不是靠「ack 比 Agent 快」
        #    的侥幸。ack 失败也不阻塞结果（用户宁可只看到结果，也不该什么都收不到）。
        await self._await_ack(metadata.get("ack_task"))

        text = result.reply_text or _EMPTY_FALLBACK
        ok = await self._send_with_retry(message_id, text)

        # ② 投递结果本身也要留痕：成功记 info，彻底失败记 error（含终态与原因），
        #    这是「绝不静默」在可观测层的那一半——用户没收到时，日志里必须查得到。
        log = logger.info if ok else logger.error
        log(
            "终态投递%s" % ("成功" if ok else "失败"),
            extra={
                "status": result.status.value,
                "message_id": message_id,
                "session_id": result.task.session_id if result.task else None,
                "error": result.error,
            },
        )

    async def _await_ack(self, ack_task: Any) -> None:
        """等待用户可见 ack 完成；它失败或被取消都不影响结果投递。"""
        if ack_task is None:
            return
        try:
            await ack_task
        except Exception:  # noqa: BLE001 —— ack 失败已在自己那层记过日志
            logger.warning("等待 ack 时出错，继续投递结果", exc_info=True)
        except asyncio.CancelledError:
            # ack 被取消不代表本任务被取消，不要向上传播（否则结果就投不出去了）。
            logger.warning("ack 任务被取消，继续投递结果")

    async def _send_with_retry(self, message_id: str, text: str) -> bool:
        """投递并在失败时重试。

        投递是**幂等安全**的（重发一条消息最坏是用户看到两条），与工具调用的「绝不重试」
        刻意相反——那边不能重试是因为可能重复产生业务副作用。
        """
        for attempt in range(self._max_retries + 1):
            if await self._sender.reply_text(message_id, text):
                return True
            if attempt < self._max_retries:
                logger.warning(
                    "投递失败，准备重试",
                    extra={"message_id": message_id, "attempt": attempt + 1},
                )
                await self._sleep(DEFAULT_RETRY_DELAY * (attempt + 1))
        return False


def is_terminal(status: TaskStatus) -> bool:
    """五种终态都需要投递——本函数存在的意义是让「有没有漏掉一种」可被测试枚举。"""
    return status in {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.TIMEOUT,
        TaskStatus.GUARDRAIL_EXHAUSTED,
        TaskStatus.BUSY,
    }
