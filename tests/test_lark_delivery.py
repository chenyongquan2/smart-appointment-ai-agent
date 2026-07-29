"""终态投递的离线确定性单测（change: feishu-channel-integration，tasks 3.5/3.7）。

核心是「绝不静默」：五种终态**每一种**都必须投出一条用户可读的回复，投不出去也必须留下
可排查的错误日志。另覆盖 ack 先于结果的顺序保证、投递失败重试、以及 delivery 自身出错
不把 executor 的 worker 带崩。
"""

from __future__ import annotations

import asyncio
from typing import List, Optional, Tuple

import pytest

from channels.lark.delivery import DEFAULT_MAX_RETRIES, LarkDelivery
from executor import Task, TaskExecutor, TaskResult, TaskStatus
from executor.local import BUSY_REPLY, TIMEOUT_REPLY
from harness.runtime.agent_loop import RunOutcome

MSG_ID = "om_x100b69419a398ca0c3846178932dd84"


class FakeSender:
    """记录投递；``fail_times`` 控制前 N 次失败以驱动重试路径。"""

    def __init__(self, fail_times: int = 0, always_fail: bool = False) -> None:
        self.calls: List[Tuple[str, str]] = []
        self.kwargs: List[dict] = []
        self._fail_times = fail_times
        self._always_fail = always_fail

    async def reply(self, message_id: str, text: str, **kwargs) -> bool:
        self.calls.append((message_id, text))
        self.kwargs.append(kwargs)
        if self._always_fail:
            return False
        if self._fail_times > 0:
            self._fail_times -= 1
            return False
        return True


async def _no_sleep(_seconds: float) -> None:
    return None


def make_task(ack_task: Optional[object] = None, message_id: Optional[str] = MSG_ID) -> Task:
    metadata = {"chat_id": "oc_x", "event_id": "evt-1"}
    if message_id is not None:
        metadata["message_id"] = message_id
    if ack_task is not None:
        metadata["ack_task"] = ack_task
    return Task(session_id="feishu:om_a", user_input="你好", user_id="ou_sender",
                channel="feishu", metadata=metadata)


def result(status: TaskStatus, reply: str = "好的", **kw) -> TaskResult:
    return TaskResult(status, reply, task=kw.pop("task", make_task()), **kw)


# --------------------------------------------------------------------------- #
# 绝不静默：五种终态逐一投递
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
@pytest.mark.parametrize("status", list(TaskStatus))
async def test_every_terminal_state_gets_delivered(status):
    """参数化跑遍 TaskStatus 的**全部**成员——日后新增终态若忘了投递，这条会挂。"""
    sender = FakeSender()
    delivery = LarkDelivery(sender, sleep=_no_sleep)

    await delivery(result(status, reply=f"{status.value} 的回复"))

    assert len(sender.calls) == 1
    assert sender.calls[0] == (MSG_ID, f"{status.value} 的回复")


@pytest.mark.asyncio
async def test_result_is_sent_as_rich_text_in_thread():
    """结果走富文本卡片（否则 Agent 的 markdown 会原样显示星号），且进话题。"""
    sender = FakeSender()

    await LarkDelivery(sender, sleep=_no_sleep)(
        result(TaskStatus.SUCCEEDED, reply="**加粗**的回复")
    )

    assert sender.kwargs[0].get("rich") is True
    assert sender.kwargs[0].get("in_thread") is not False


@pytest.mark.asyncio
async def test_timeout_text_warns_about_side_effects():
    """超时可能发生在 create_appointment 写库之后，文案必须提示、且系统不自动重试。"""
    sender = FakeSender()

    await LarkDelivery(sender, sleep=_no_sleep)(
        result(TaskStatus.TIMEOUT, reply=TIMEOUT_REPLY)
    )

    text = sender.calls[0][1]
    assert "重复" in text
    assert len(sender.calls) == 1  # 只投一次，绝不重跑任务


@pytest.mark.asyncio
async def test_busy_rejection_is_also_delivered():
    sender = FakeSender()

    await LarkDelivery(sender, sleep=_no_sleep)(
        result(TaskStatus.BUSY, reply=BUSY_REPLY)
    )

    assert sender.calls[0][1] == BUSY_REPLY


@pytest.mark.asyncio
async def test_empty_reply_never_sends_blank():
    """空回复既是静默，飞书也会拒收空内容——必须换成兜底文案。"""
    sender = FakeSender()

    await LarkDelivery(sender, sleep=_no_sleep)(result(TaskStatus.SUCCEEDED, reply=""))

    assert sender.calls[0][1].strip() != ""


# --------------------------------------------------------------------------- #
# ack 先于结果
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_result_waits_for_ack():
    """顺序保证来自 await ack_task，而不是「ack 比 Agent 快」的侥幸。"""
    order: List[str] = []

    async def slow_ack() -> bool:
        await asyncio.sleep(0.03)
        order.append("ack")
        return True

    ack = asyncio.ensure_future(slow_ack())

    class OrderRecordingSender:
        async def reply(self, message_id: str, text: str, **kwargs) -> bool:
            order.append("result")
            return True

    await LarkDelivery(OrderRecordingSender(), sleep=_no_sleep)(
        result(TaskStatus.SUCCEEDED, task=make_task(ack_task=ack))
    )

    assert order == ["ack", "result"]


@pytest.mark.asyncio
async def test_failed_ack_does_not_block_result():
    """ack 发不出去时，用户宁可只看到结果，也不该什么都收不到。"""
    async def boom() -> bool:
        raise RuntimeError("ack 挂了")

    ack = asyncio.ensure_future(boom())
    sender = FakeSender()

    await LarkDelivery(sender, sleep=_no_sleep)(
        result(TaskStatus.SUCCEEDED, task=make_task(ack_task=ack))
    )

    assert len(sender.calls) == 1


@pytest.mark.asyncio
async def test_cancelled_ack_does_not_cancel_delivery():
    """ack 被取消不代表任务被取消——CancelledError 不该向上传播掉结果投递。"""
    async def forever() -> bool:
        await asyncio.sleep(3600)
        return True

    ack = asyncio.ensure_future(forever())
    await asyncio.sleep(0)
    ack.cancel()
    sender = FakeSender()

    await LarkDelivery(sender, sleep=_no_sleep)(
        result(TaskStatus.SUCCEEDED, task=make_task(ack_task=ack))
    )

    assert len(sender.calls) == 1


# --------------------------------------------------------------------------- #
# 重试
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_retries_until_success():
    sender = FakeSender(fail_times=2)

    await LarkDelivery(sender, sleep=_no_sleep)(result(TaskStatus.SUCCEEDED))

    assert len(sender.calls) == 3  # 首次 + 2 次重试


@pytest.mark.asyncio
async def test_retry_count_is_bounded():
    """重试有上限：投不出去就记 error 收场，不能无限重发把群刷爆。"""
    sender = FakeSender(always_fail=True)

    await LarkDelivery(sender, sleep=_no_sleep)(result(TaskStatus.SUCCEEDED))

    assert len(sender.calls) == DEFAULT_MAX_RETRIES + 1


@pytest.mark.asyncio
async def test_delivery_is_retried_but_tasks_are_not():
    """投递可重试（重发消息最坏是用户看到两条），与工具调用的「绝不重试」刻意相反——
    那边不能重试是因为可能重复产生业务副作用。"""
    sender = FakeSender(fail_times=1)

    await LarkDelivery(sender, sleep=_no_sleep)(result(TaskStatus.SUCCEEDED, reply="同一条"))

    assert [t for _, t in sender.calls] == ["同一条", "同一条"]


# --------------------------------------------------------------------------- #
# 异常收口
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_missing_reply_target_does_not_raise():
    """没有 message_id 时真投不出去，但不能抛异常，也不能悄悄咽下（记 error）。"""
    sender = FakeSender()

    await LarkDelivery(sender, sleep=_no_sleep)(
        result(TaskStatus.SUCCEEDED, task=make_task(message_id=None))
    )

    assert sender.calls == []


@pytest.mark.asyncio
async def test_sender_exception_is_contained():
    class ExplodingSender:
        async def reply(self, message_id: str, text: str, **kwargs) -> bool:
            raise RuntimeError("网络炸了")

    # 不抛出即通过：delivery 崩了不该把 executor 的 worker 带走。
    await LarkDelivery(ExplodingSender(), sleep=_no_sleep)(result(TaskStatus.SUCCEEDED))


@pytest.mark.asyncio
async def test_result_without_task_does_not_raise():
    await LarkDelivery(FakeSender(), sleep=_no_sleep)(
        TaskResult(TaskStatus.FAILED, "出错了", task=None)
    )


# --------------------------------------------------------------------------- #
# 与 executor 的接线
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_wired_as_executor_callback_end_to_end():
    """delivery 作为 executor 的终态回调直接接上，走一遍真实调用链。"""
    async def runner(task, on_outcome):
        on_outcome(RunOutcome.COMPLETED)
        yield "[REPLY]已为你预约"

    sender = FakeSender()
    delivery = LarkDelivery(sender, sleep=_no_sleep)
    executor = TaskExecutor(runner)

    done = asyncio.Event()

    async def on_complete(res):
        await delivery(res)
        done.set()

    executor.submit(make_task(), on_complete)
    await asyncio.wait_for(done.wait(), timeout=5.0)

    assert sender.calls == [(MSG_ID, "已为你预约")]
