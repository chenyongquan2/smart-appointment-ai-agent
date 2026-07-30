"""进程内 asyncio 任务执行层（change: feishu-channel-integration，设计见 design.md D2）。

提供两种执行模式，**共享同一套并发记账**（同一全局 Semaphore + 同一把 per-session 锁），
故「同话题串行 / 跨话题并行 / 并发上限 / 排队深度上限」对两条路径同等生效：

- ``execute_inline(task)``：在**调用方自己的协程里**跑，直接透传 token 流。Web 用。
- ``submit(task, on_complete)``：入队，由 worker 协程异步执行，终态经回调通知。IM 用。

为什么 Web 不走队列（这是本模块最容易被"统一"掉的设计）：把 Web 改成「worker 产 token
→ 队列 → 请求协程消费」会凭空引入三个当前不存在的问题——背压（无界队列会涨、有界会卡
worker）、断连语义（浏览器关页面时 worker 是跑完还是被取消，直接影响 assistant 回合是否
落库）、异常跨协程重抛。而本期的硬要求恰恰是 Web 对外行为不变。inline 模式下透传的还是
同一个 async generator，"行为不变"在构造上成立，不需要靠测试证明。

接口抽象并未因此打折：将来 executor 拆成独立服务时，inline 本就要退化为 submit + SSE。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, AsyncIterator, Callable, Optional

from executor.task import Task, TaskResult, TaskStatus
from harness.runtime.agent_loop import RunOutcome

logger = logging.getLogger(__name__)

# 与 AgentLoop 的约定前缀。**协议解析归 executor**：Channel 只读 TaskResult 的字段。
_REPLY_PREFIX = "[REPLY]"

DEFAULT_MAX_CONCURRENCY = 10       # 跨会话并行上限
DEFAULT_MAX_QUEUE_PER_SESSION = 5  # 单会话等待队列深度上限
DEFAULT_WALL_CLOCK_TIMEOUT = 600.0 # 任务墙钟总超时（秒）

# 非成功终态的用户可见文案。超时那条**必须**提示副作用风险：取消可能发生在
# create_appointment 已写库之后、回复生成之前，此时预约真的建了而用户看到的是超时。
# 根治要给危险工具做幂等键（另一期），本期只能诚实告知且绝不自动重试。
TIMEOUT_REPLY = "抱歉，本次处理超时了，已中断。若此前已产生预约，请勿重复操作，可先向我确认。"
FAILED_REPLY = "抱歉，处理这条消息时出错了，请稍后再试或换种说法。"
BUSY_REPLY = "我这边还在处理你前面的消息，先歇口气——请稍后再发。"

# runner 协议：给一个任务 + 一个 outcome 回调，产出 token 流。
# 之所以把 outcome 单独作回调而不是从 token 流里认，是因为 AgentLoop 在「打转 / 预算超支 /
# 重试耗尽 / 跑满步数」四种情况下 yield 的是**同一句**兜底文案，靠比对字符串来反推正是
# 黄金准则禁止的脆弱解析（见 RunOutcome 的 docstring）。
Runner = Callable[[Task, Callable[[RunOutcome], None]], AsyncGenerator[str, None]]


class SessionBusy(Exception):
    """该会话等待队列已满，任务未入队。"""


class TaskExecutor:
    """进程内 asyncio 任务执行层。

    Args:
        runner: 真正执行一个任务的异步生成器工厂（生产接线为 ``chat_handler``）。
        max_concurrency: 全局并发上限（默认 10）。
        max_queue_per_session: 单会话等待队列深度上限（默认 5）。超出即拒绝入队——
            同话题串行下用户连发 N 条会排出 N 个任务并投递 N 条回复，既刷屏又白烧 token。
        wall_clock_timeout: 任务墙钟总超时秒数（默认 600）；``None`` 时不限时。
    """

    def __init__(
        self,
        runner: Runner,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        max_queue_per_session: int = DEFAULT_MAX_QUEUE_PER_SESSION,
        wall_clock_timeout: Optional[float] = DEFAULT_WALL_CLOCK_TIMEOUT,
    ) -> None:
        self._runner = runner
        self._max_concurrency = max_concurrency
        self._max_queue_per_session = max_queue_per_session
        self._wall_clock_timeout = wall_clock_timeout
        # 延迟创建：Semaphore 要绑定运行中的事件循环，构造 executor 时可能还没有。
        self._sem: Optional[asyncio.Semaphore] = None
        # 每会话一把锁 = 同话题串行的实现；waiting 计的是「正等这把锁」的任务数。
        self._locks: dict[str, asyncio.Lock] = {}
        self._waiting: dict[str, int] = {}
        # 持有在途 worker 任务的强引用：否则 asyncio 可能在任务跑完前把它回收掉。
        self._workers: set[asyncio.Task] = set()

    # ── 并发记账 ────────────────────────────────────────────────────────────
    @asynccontextmanager
    async def _slot(self, session_id: str) -> AsyncIterator[None]:
        """占住「该会话的串行锁 + 一个全局并发名额」。

        取锁**先于**取信号量，顺序是刻意的：反过来的话，同会话的后来者会先攥着一个并发
        名额再去等锁，白占额度。现在的顺序下，等锁的任务不消耗并发名额。
        """
        lock = self._locks.setdefault(session_id, asyncio.Lock())

        # 排队深度判定：锁被占着说明有任务在跑，此时的 waiting 就是队列长度。
        if lock.locked() and self._waiting.get(session_id, 0) >= self._max_queue_per_session:
            raise SessionBusy(session_id)

        self._waiting[session_id] = self._waiting.get(session_id, 0) + 1
        try:
            await lock.acquire()
        finally:
            self._waiting[session_id] -= 1

        if self._sem is None:
            self._sem = asyncio.Semaphore(self._max_concurrency)
        try:
            async with self._sem:
                yield
        finally:
            lock.release()
            # 无人持有、无人等待时回收，避免 session 字典随会话数无界增长。
            if not lock.locked() and not self._waiting.get(session_id):
                self._locks.pop(session_id, None)
                self._waiting.pop(session_id, None)

    # ── 墙钟超时 ────────────────────────────────────────────────────────────
    async def _iter_with_deadline(
        self, agen: AsyncGenerator[str, None], deadline: Optional[float]
    ) -> AsyncGenerator[str, None]:
        """迭代 token 流并施加墙钟上限；超时抛 ``asyncio.TimeoutError``。

        逐个 ``__anext__`` 套 ``wait_for``（而非把整体包起来）是因为被执行的是异步生成器，
        没法整体 ``wait_for``。超时会取消当前挂起的 ``__anext__``，于是 ``CancelledError``
        被抛进生成器内部它正停着的 await 点——编排层（``chat_handler``）据此补写兜底
        assistant 回合再重抛，会话历史因而不会留下配不上回复的孤立 user 回合。
        """
        try:
            while True:
                if deadline is None:
                    remaining: Optional[float] = None
                else:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                try:
                    token = await asyncio.wait_for(agen.__anext__(), remaining)
                except StopAsyncIteration:
                    return
                yield token
        finally:
            # 消费方提前退出（如客户端断连）时也要关掉生成器，让编排层的收尾逻辑跑到。
            await agen.aclose()

    def _deadline(self) -> Optional[float]:
        if self._wall_clock_timeout is None:
            return None
        return asyncio.get_running_loop().time() + self._wall_clock_timeout

    # ── 模式一：同步内联（Web） ─────────────────────────────────────────────
    async def execute_inline(self, task: Task) -> AsyncGenerator[str, None]:
        """在调用方协程内执行并透传 token 流。

        终态不走回调——调用方就在现场。超时与忙碌以一条 ``[REPLY]`` 兜底文案收尾，
        保持与前端既有的输出协议一致（而非让 HTTP 流以异常截断）。
        """
        try:
            async with self._slot(task.session_id):
                agen = self._runner(task, lambda outcome: None)
                stream = self._iter_with_deadline(agen, self._deadline())
                # 显式 aclose 而非只靠 async for 退出：``async for`` 被异常/GeneratorExit
                # 打断时**不会**关闭迭代对象，内层生成器会一直挂着，直到事件循环收尾时才被
                # 终结。而客户端断连正是走这条路——收尾逻辑（补写兜底回合）必须当场跑到。
                try:
                    async for token in stream:
                        yield token
                finally:
                    await stream.aclose()
        except SessionBusy:
            yield f"{_REPLY_PREFIX}{BUSY_REPLY}"
        except asyncio.TimeoutError:
            logger.warning("任务墙钟超时（inline）", extra={"session_id": task.session_id})
            yield f"{_REPLY_PREFIX}{TIMEOUT_REPLY}"

    # ── 模式二：异步提交（IM） ──────────────────────────────────────────────
    def submit(
        self,
        task: Task,
        on_complete: Callable[[TaskResult], Any],
    ) -> str:
        """提交任务并立即返回 task_id；终态经 ``on_complete`` 回调通知。

        回调**一定会被调用恰好一次**（五种终态之一）——这是 Channel「绝不静默」的地基。
        """
        task_id = uuid.uuid4().hex
        worker = asyncio.create_task(self._work(task, on_complete), name=f"task-{task_id}")
        # 强引用直到跑完：否则事件循环只持弱引用，任务可能被中途回收。
        self._workers.add(worker)
        worker.add_done_callback(self._workers.discard)
        return task_id

    async def _work(self, task: Task, on_complete: Callable[[TaskResult], Any]) -> None:
        result = await self._run_to_result(task)
        try:
            outcome = on_complete(result)
            if asyncio.iscoroutine(outcome):
                await outcome
        except Exception:  # noqa: BLE001 —— 投递侧自己出错不该把 worker 也带崩
            logger.exception("终态回调失败", extra={"session_id": task.session_id})

    async def _run_to_result(self, task: Task) -> TaskResult:
        """跑完一个任务，收敛成结构化终态。"""
        outcome_box: dict[str, RunOutcome] = {}
        reply = ""
        try:
            async with self._slot(task.session_id):
                agen = self._runner(task, lambda o: outcome_box.__setitem__("outcome", o))
                async for token in self._iter_with_deadline(agen, self._deadline()):
                    # 只有 [REPLY] 那条是最终回复；多次出现时以最后一条为准（与 chat_handler 一致）。
                    if token.startswith(_REPLY_PREFIX):
                        reply = token[len(_REPLY_PREFIX):]
        except SessionBusy:
            return TaskResult(TaskStatus.BUSY, BUSY_REPLY, task=task)
        except asyncio.TimeoutError:
            logger.warning("任务墙钟超时", extra={"session_id": task.session_id})
            return TaskResult(TaskStatus.TIMEOUT, TIMEOUT_REPLY,
                              error="wall clock timeout", task=task)
        except Exception as exc:  # noqa: BLE001 —— 任何异常都要变成可投递的终态
            logger.exception("任务执行失败", extra={"session_id": task.session_id})
            return TaskResult(TaskStatus.FAILED, FAILED_REPLY, error=repr(exc), task=task)

        return self._classify(outcome_box.get("outcome"), reply, task)

    @staticmethod
    def _classify(outcome: Optional[RunOutcome], reply: str, task: Task) -> TaskResult:
        """把 loop 的带外 outcome 映射成任务终态。

        护栏拦停（打转 / 预算 / 重试耗尽 / 跑满步数）算**失败**而非成功：用户拿到的是
        一句「没能完成」的兜底文案，把它记成成功会让日后的成功率指标虚高。但回复照投——
        终态是失败，不等于可以静默。
        """
        if outcome is RunOutcome.GUARDRAIL_EXHAUSTED:
            return TaskResult(TaskStatus.GUARDRAIL_EXHAUSTED, reply,
                              error="guardrail exhausted", task=task)
        if outcome is not None and outcome is not RunOutcome.COMPLETED:
            return TaskResult(TaskStatus.FAILED, reply, error=outcome.value, task=task)
        return TaskResult(TaskStatus.SUCCEEDED, reply, task=task)
