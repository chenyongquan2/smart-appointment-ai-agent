"""LLM 调用护栏：超时 + 指数退避重试（Phase 5）。

``guarded_invoke`` 对一次异步 LLM 调用施加：
- **超时**：单次调用经 ``asyncio.wait_for`` 限时，超时即视为本次失败；
- **重试**：对超时与瞬时连接类异常按指数退避（``base_delay × 2**n``）重试，最多
  ``max_attempts`` 次；退避等待经可注入的 ``sleep`` 完成（测试传 no-op，不真睡）。

重试耗尽后抛出明确的 :class:`GuardrailExhausted`（而非让底层异常冒泡），由调用方
（``AgentLoop``）捕获并转为优雅降级的兜底回复。

设计要点（见 OpenSpec change phase-5-guardrails 的 design.md D1/D2）：超时与重试逻辑
紧耦合，合在本文件内（timeout 作为 retry 的参数）；只包裹**只读、幂等**的 LLM 调用，
带副作用的工具调用 MUST NOT 经此重试（避免重复执行写操作）。
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional, TypeVar

T = TypeVar("T")

# 默认护栏参数（``AgentLoop`` 可经构造参数覆盖）。
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 0.5

# 可重试的瞬时异常：超时与连接类。其它异常视为不可重试，直接冒泡。
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    asyncio.TimeoutError,
    TimeoutError,
    ConnectionError,
)


class GuardrailExhausted(Exception):
    """LLM 调用经超时 + 重试护栏后仍失败，重试已耗尽。"""


async def guarded_invoke(
    call: Callable[[], Awaitable[T]],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    sleep: Optional[Callable[[float], Awaitable[None]]] = None,
) -> T:
    """带超时与指数退避重试地执行一次异步调用。

    Args:
        call: 零参 async thunk，每次重试都重新调用它发起一次新的请求。
        timeout: 单次调用的超时秒数。
        max_attempts: 最大尝试次数（含首次）；≥1。
        base_delay: 指数退避基准秒数；第 n 次重试前等待 ``base_delay × 2**(n-1)``。
        sleep: 退避等待实现（默认 ``asyncio.sleep``）；测试可注入 no-op 避免真实等待。

    Returns:
        ``call`` 成功时的返回值。

    Raises:
        GuardrailExhausted: 所有尝试均因可重试异常失败时抛出，``__cause__`` 为最后一次异常。
    """
    sleep_fn = sleep or asyncio.sleep
    last_exc: Optional[BaseException] = None

    for attempt in range(max_attempts):
        try:
            return await asyncio.wait_for(call(), timeout=timeout)
        except RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            # 还有剩余尝试则退避后重试；否则跳出转 GuardrailExhausted。
            if attempt + 1 < max_attempts:
                await sleep_fn(base_delay * (2 ** attempt))

    raise GuardrailExhausted(
        f"LLM 调用重试 {max_attempts} 次仍失败：{last_exc!r}"
    ) from last_exc
