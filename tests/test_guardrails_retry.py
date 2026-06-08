"""guarded_invoke 单测（Phase 5）：超时 + 指数退避重试，全程离线、无真实等待。

退避用注入的 no-op sleep，超时用极小 timeout 包裹一个长等待，使测试快速且确定。
"""

from __future__ import annotations

import asyncio

import pytest

from harness.guardrails.retry import GuardrailExhausted, guarded_invoke


async def _noop_sleep(_delay: float) -> None:
    """no-op 退避：测试中不产生真实等待。"""
    return None


@pytest.mark.asyncio
async def test_first_call_succeeds_no_retry():
    sleeps: list[float] = []

    async def _sleep(d: float) -> None:
        sleeps.append(d)

    async def _ok() -> str:
        return "ok"

    result = await guarded_invoke(_ok, sleep=_sleep)

    assert result == "ok"
    assert sleeps == []  # 未发生任何退避/重试


@pytest.mark.asyncio
async def test_retries_then_succeeds():
    attempts = {"n": 0}
    sleeps: list[float] = []

    async def _sleep(d: float) -> None:
        sleeps.append(d)

    async def _flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("瞬时连接失败")
        return "recovered"

    result = await guarded_invoke(
        _flaky, max_attempts=3, base_delay=0.5, sleep=_sleep
    )

    assert result == "recovered"
    assert attempts["n"] == 3
    # 两次重试，指数退避：0.5 * 2**0, 0.5 * 2**1
    assert sleeps == [0.5, 1.0]


@pytest.mark.asyncio
async def test_timeout_triggers_retry():
    attempts = {"n": 0}

    async def _slow() -> str:
        attempts["n"] += 1
        await asyncio.sleep(5)  # 远超 timeout，被 wait_for 取消 → TimeoutError
        return "never"

    with pytest.raises(GuardrailExhausted):
        await guarded_invoke(
            _slow, timeout=0.01, max_attempts=2, sleep=_noop_sleep
        )

    assert attempts["n"] == 2  # 每次超时都重试，恰好 max_attempts 次


@pytest.mark.asyncio
async def test_exhausted_raises_guardrail_exhausted():
    async def _always_fail() -> str:
        raise ConnectionError("一直失败")

    with pytest.raises(GuardrailExhausted) as exc_info:
        await guarded_invoke(_always_fail, max_attempts=3, sleep=_noop_sleep)

    # 原始异常作为 __cause__ 保留，不让其裸冒泡
    assert isinstance(exc_info.value.__cause__, ConnectionError)


@pytest.mark.asyncio
async def test_non_retryable_exception_not_retried():
    attempts = {"n": 0}

    async def _bad() -> str:
        attempts["n"] += 1
        raise ValueError("不可重试的程序错误")

    with pytest.raises(ValueError):
        await guarded_invoke(_bad, max_attempts=3, sleep=_noop_sleep)

    assert attempts["n"] == 1  # 不可重试异常立即冒泡，不重试
