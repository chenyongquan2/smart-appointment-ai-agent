"""任务执行层的离线确定性单测（change: feishu-channel-integration，tasks 1.8）。

覆盖：同话题串行、跨话题并行、并发上限排队、排队深度上限拒绝、墙钟超时、
五种终态回调、outcome→终态映射、取消信号传播、两种模式共享同一套并发记账。
全程注入 fake runner，不触网、不碰 DB；用极小时延不真等。
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Callable, List

import pytest

from executor import Task, TaskExecutor, TaskStatus
from executor.local import BUSY_REPLY, TIMEOUT_REPLY
from harness.runtime.agent_loop import RunOutcome

REPLY = "[REPLY]"


# --------------------------------------------------------------------------- #
# fake runners
# --------------------------------------------------------------------------- #
def make_runner(
    delay: float = 0.0,
    reply: str = "好的",
    outcome: RunOutcome = RunOutcome.COMPLETED,
    raises: BaseException | None = None,
    trace: List[str] | None = None,
):
    """构造一个 fake runner；trace 传入时记录 start/end 以观察串行与并行。"""

    async def _runner(task: Task, on_outcome: Callable[[RunOutcome], None]) -> AsyncGenerator[str, None]:
        if trace is not None:
            trace.append(f"start:{task.session_id}")
        try:
            yield "[THOUGHT]思考中"
            if raises is not None:
                raise raises
            if delay:
                await asyncio.sleep(delay)
            on_outcome(outcome)
            yield f"{REPLY}{reply}"
        finally:
            if trace is not None:
                trace.append(f"end:{task.session_id}")

    return _runner


def task(session_id: str = "s1", text: str = "你好") -> Task:
    return Task(session_id=session_id, user_input=text)


async def collect(agen) -> list[str]:
    return [t async for t in agen]


async def run_and_capture(executor: TaskExecutor, t: Task):
    """submit 一个任务并等它的终态回调。"""
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    executor.submit(t, lambda result: fut.set_result(result))
    return await asyncio.wait_for(fut, timeout=5.0)


# --------------------------------------------------------------------------- #
# 终态
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_submit_reports_success_with_reply():
    ex = TaskExecutor(make_runner(reply="已为你预约"))
    result = await run_and_capture(ex, task())

    assert result.status is TaskStatus.SUCCEEDED
    assert result.reply_text == "已为你预约"  # [REPLY] 前缀由 executor 剥掉，Channel 不碰协议
    assert result.task is not None and result.task.session_id == "s1"


@pytest.mark.asyncio
async def test_runner_exception_maps_to_failed_with_user_visible_text():
    ex = TaskExecutor(make_runner(raises=RuntimeError("boom")))
    result = await run_and_capture(ex, task())

    assert result.status is TaskStatus.FAILED
    assert result.reply_text  # 绝不静默：失败也要有一句能投递给用户的话
    assert "boom" in (result.error or "")


@pytest.mark.asyncio
async def test_wall_clock_timeout_maps_to_timeout_terminal_state():
    ex = TaskExecutor(make_runner(delay=5.0), wall_clock_timeout=0.02)
    result = await run_and_capture(ex, task())

    assert result.status is TaskStatus.TIMEOUT
    assert result.reply_text == TIMEOUT_REPLY


@pytest.mark.asyncio
async def test_timeout_reply_warns_about_side_effects():
    """超时文案必须提示副作用风险：取消可能落在 create_appointment 写库之后。"""
    assert "重复" in TIMEOUT_REPLY


@pytest.mark.asyncio
async def test_guardrail_exhausted_is_its_own_terminal_state():
    ex = TaskExecutor(make_runner(outcome=RunOutcome.GUARDRAIL_EXHAUSTED, reply="抱歉…"))
    result = await run_and_capture(ex, task())

    assert result.status is TaskStatus.GUARDRAIL_EXHAUSTED
    assert result.reply_text == "抱歉…"  # 终态是失败，但回复照投


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [RunOutcome.SPIN_DETECTED,
                                     RunOutcome.MAX_STEPS,
                                     RunOutcome.BUDGET_EXCEEDED])
async def test_guardrail_stops_are_not_counted_as_success(outcome):
    """护栏拦停算失败——记成成功会让日后的任务成功率指标虚高。"""
    ex = TaskExecutor(make_runner(outcome=outcome))
    result = await run_and_capture(ex, task())

    assert result.status is TaskStatus.FAILED
    assert result.error == outcome.value


@pytest.mark.asyncio
async def test_callback_failure_does_not_crash_worker():
    """投递侧自己抛异常不该把 worker 带崩（否则一个坏回调会拖垮后续任务）。"""
    ex = TaskExecutor(make_runner())
    done = asyncio.Event()

    def _bad(result):
        done.set()
        raise RuntimeError("delivery exploded")

    ex.submit(task(), _bad)
    await asyncio.wait_for(done.wait(), timeout=5.0)
    # worker 静默收敛后，executor 仍可正常接新任务
    assert (await run_and_capture(ex, task("s2"))).status is TaskStatus.SUCCEEDED


# --------------------------------------------------------------------------- #
# 串行 / 并行 / 并发上限
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_same_session_runs_serially():
    trace: List[str] = []
    ex = TaskExecutor(make_runner(delay=0.02, trace=trace))

    await asyncio.gather(run_and_capture(ex, task("s1")), run_and_capture(ex, task("s1")))

    # 严格交替：第二个任务必须等第一个结束后才开始
    assert trace == ["start:s1", "end:s1", "start:s1", "end:s1"]


@pytest.mark.asyncio
async def test_different_sessions_run_in_parallel():
    trace: List[str] = []
    ex = TaskExecutor(make_runner(delay=0.05, trace=trace))

    await asyncio.gather(run_and_capture(ex, task("a")), run_and_capture(ex, task("b")))

    # 两个 start 都排在任何 end 之前 → 确实同时在跑
    assert trace[0].startswith("start") and trace[1].startswith("start")


@pytest.mark.asyncio
async def test_concurrency_cap_queues_rather_than_drops():
    """并发达上限时新任务排队等待，MUST NOT 被丢弃。"""
    running = 0
    peak = 0

    async def _runner(t: Task, on_outcome) -> AsyncGenerator[str, None]:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        try:
            await asyncio.sleep(0.02)
            on_outcome(RunOutcome.COMPLETED)
            yield f"{REPLY}ok"
        finally:
            running -= 1

    ex = TaskExecutor(_runner, max_concurrency=2)
    results = await asyncio.gather(*(run_and_capture(ex, task(f"s{i}")) for i in range(6)))

    assert peak <= 2                                  # 上限被遵守
    assert len(results) == 6                          # 一个都没丢
    assert all(r.status is TaskStatus.SUCCEEDED for r in results)


@pytest.mark.asyncio
async def test_waiting_tasks_do_not_consume_concurrency_slots():
    """等会话锁的任务不该占并发名额——否则同话题排队会饿死其它话题。

    取锁先于取信号量的顺序就是为这条：并发上限设为 1 时，同会话排队的第二个任务若
    先攥住信号量再等锁，另一个会话的任务将永远拿不到名额。
    """
    trace: List[str] = []
    ex = TaskExecutor(make_runner(delay=0.02, trace=trace), max_concurrency=1)

    await asyncio.wait_for(
        asyncio.gather(run_and_capture(ex, task("s1")),
                       run_and_capture(ex, task("s1")),
                       run_and_capture(ex, task("other"))),
        timeout=5.0,  # 若发生饿死，这里会超时
    )
    assert trace.count("start:other") == 1


# --------------------------------------------------------------------------- #
# 排队深度上限
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_queue_depth_limit_rejects_with_busy():
    ex = TaskExecutor(make_runner(delay=0.05), max_queue_per_session=1)

    results = await asyncio.gather(*(run_and_capture(ex, task("s1")) for _ in range(4)))
    statuses = [r.status for r in results]

    assert TaskStatus.BUSY in statuses                       # 超出的被拒
    assert statuses.count(TaskStatus.SUCCEEDED) == 2         # 1 个在跑 + 1 个排队
    busy = next(r for r in results if r.status is TaskStatus.BUSY)
    assert busy.reply_text == BUSY_REPLY                     # 拒绝也要有回复，不静默


@pytest.mark.asyncio
async def test_queue_depth_limit_is_per_session():
    """一个会话被打满，不该影响别的会话。"""
    ex = TaskExecutor(make_runner(delay=0.03), max_queue_per_session=1)

    flood = [run_and_capture(ex, task("noisy")) for _ in range(4)]
    quiet = run_and_capture(ex, task("quiet"))
    results = await asyncio.gather(*flood, quiet)

    assert results[-1].status is TaskStatus.SUCCEEDED


# --------------------------------------------------------------------------- #
# 内联模式（Web）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_execute_inline_passes_tokens_through_verbatim():
    """内联模式逐字节透传 token 流——[REPLY] 前缀保留，前端解析不变。"""
    ex = TaskExecutor(make_runner(reply="好的"))

    tokens = await collect(ex.execute_inline(task()))

    assert tokens == ["[THOUGHT]思考中", "[REPLY]好的"]


@pytest.mark.asyncio
async def test_execute_inline_timeout_yields_fallback_reply():
    """内联超时以一条 [REPLY] 收尾，而不是让 HTTP 流以异常截断。"""
    ex = TaskExecutor(make_runner(delay=5.0), wall_clock_timeout=0.02)

    tokens = await collect(ex.execute_inline(task()))

    assert tokens[-1] == f"{REPLY}{TIMEOUT_REPLY}"


@pytest.mark.asyncio
async def test_inline_and_submit_share_the_same_serialization():
    """两种模式共享同一把会话锁——否则 Web 与飞书可能同时改同一条会话历史。"""
    trace: List[str] = []
    ex = TaskExecutor(make_runner(delay=0.03, trace=trace))

    await asyncio.gather(collect(ex.execute_inline(task("shared"))),
                         run_and_capture(ex, task("shared")))

    assert trace == ["start:shared", "end:shared", "start:shared", "end:shared"]


# --------------------------------------------------------------------------- #
# 取消语义
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_timeout_cancels_inside_the_runner():
    """墙钟超时把 CancelledError 抛进 runner 内部它正停着的 await 点。

    编排层正是靠这个信号补写兜底 assistant 回合的——若超时改成「等它自己跑完」，
    会话历史就会留下配不上回复的孤立 user 回合。
    """
    cancelled = asyncio.Event()

    async def _runner(t: Task, on_outcome) -> AsyncGenerator[str, None]:
        try:
            await asyncio.sleep(5.0)
            yield f"{REPLY}never"
        except asyncio.CancelledError:
            cancelled.set()
            raise

    ex = TaskExecutor(_runner, wall_clock_timeout=0.02)
    result = await run_and_capture(ex, task())

    assert result.status is TaskStatus.TIMEOUT
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_generator_is_closed_when_consumer_stops_early():
    """消费方提前退出（客户端断连）时生成器被关闭，编排层的收尾逻辑得以跑到。"""
    closed = asyncio.Event()

    async def _runner(t: Task, on_outcome) -> AsyncGenerator[str, None]:
        try:
            yield "[THOUGHT]一"
            yield "[THOUGHT]二"
        finally:
            closed.set()

    ex = TaskExecutor(_runner)
    agen = ex.execute_inline(task())
    assert await agen.__anext__() == "[THOUGHT]一"
    await agen.aclose()

    assert closed.is_set()


# --------------------------------------------------------------------------- #
# 会话记账不泄漏
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_session_bookkeeping_is_released():
    """跑完的会话不该在锁表里留残渣——否则长期运行会随会话数无界增长。"""
    ex = TaskExecutor(make_runner())

    for i in range(5):
        await run_and_capture(ex, task(f"s{i}"))

    assert ex._locks == {}
    assert ex._waiting == {}
