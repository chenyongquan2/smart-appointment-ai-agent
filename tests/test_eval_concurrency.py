"""用例并发执行单测（change evals-concurrent-runner）。

注入 fake capture_fn（可控完成顺序与抛异常）离线断言四条硬约束：
结果同序、并发上限生效、单条失败隔离、`--concurrency 1` 等价串行。
不触网、不调真实 provider、不碰 services/。
"""

import asyncio

import pytest

from evals.agent_capture import CaptureResult


@pytest.fixture(autouse=True)
def _wire_placeholders():
    """注入 run_evals 的模块级占位（正常由 run_baseline 内按需 import 后设置）。"""
    import evals.run_evals as re
    from evals.metrics import EvalResult, slots_from_tool_calls

    re._EvalResult = EvalResult
    re._slots_from_tool_calls = slots_from_tool_calls
    yield


def _cases(n: int) -> list[dict]:
    """n 条单轮用例，输入形如 c0/c1/...（用作同序断言的标识）。"""
    return [{"turns": [f"c{i}"], "expected_intent": "other"} for i in range(n)]


@pytest.mark.asyncio
async def test_results_keep_input_order_despite_completion_order():
    """并发下结果 MUST 与输入同序——即便完成先后被人为倒置。

    下游 _split_results(cases, results) 靠 zip 同序同长拆 dev/held-out，
    顺序错乱会把 held-out 结果算进 dev 基线，故这是硬约束。
    """
    import evals.run_evals as re

    async def fake_capture(text, llm, full, subs):
        # 让后面的用例先完成：c0 睡最久、c4 几乎立刻返回 → 完成顺序与输入顺序相反。
        idx = int(text[1:])
        await asyncio.sleep((5 - idx) * 0.01)
        return CaptureResult(tool_calls=[{"name": f"tool_{idx}", "args": {}}], reply=text)

    results = await re._run_once(_cases(5), llm=None, full_registry=None, subagents=None,
                                 capture_fn=fake_capture, concurrency=5)

    assert [r.input for r in results] == ["c0", "c1", "c2", "c3", "c4"]
    # 工具也各归各位（不是只有 input 对齐、内容串了）。
    assert [r.actual_tools[0]["name"] for r in results] == [f"tool_{i}" for i in range(5)]


@pytest.mark.asyncio
async def test_concurrency_cap_is_enforced():
    """在途用例数 MUST NOT 超过 concurrency；其余排队。"""
    import evals.run_evals as re

    in_flight = 0
    peak = 0

    async def fake_capture(text, llm, full, subs):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)  # 记录观测到的最大同时在途数
        await asyncio.sleep(0.02)    # 留出重叠窗口，否则可能永远看不到并发
        in_flight -= 1
        return CaptureResult(tool_calls=[], reply=text)

    await re._run_once(_cases(12), llm=None, full_registry=None, subagents=None,
                       capture_fn=fake_capture, concurrency=3)

    assert peak <= 3          # 上限生效
    assert peak > 1           # 确实并发了（不是退化成串行）


@pytest.mark.asyncio
async def test_single_failure_does_not_cancel_others():
    """单条抛异常 → 该条记 N/A，其余照常跑完（异常在 _run_case 内被吞，不冒泡到 gather）。"""
    import evals.run_evals as re

    async def fake_capture(text, llm, full, subs):
        if text == "c2":
            raise RuntimeError("boom")
        return CaptureResult(tool_calls=[{"name": "ok", "args": {}}], reply=text)

    results = await re._run_once(_cases(5), llm=None, full_registry=None, subagents=None,
                                 capture_fn=fake_capture, concurrency=5)

    assert len(results) == 5
    failed = results[2]
    assert failed.actual_tools is None and failed.latency_s is None  # 该条 N/A，不伪造
    # 其余四条均正常产出（没被 gather 的取消波及）。
    assert all(results[i].actual_tools == [{"name": "ok", "args": {}}] for i in (0, 1, 3, 4))


@pytest.mark.asyncio
async def test_concurrency_one_is_serial_and_equivalent():
    """--concurrency 1 走串行基准路径：任一时刻仅 1 条在途，结果与并发跑一致。"""
    import evals.run_evals as re

    in_flight = 0
    peak = 0

    async def fake_capture(text, llm, full, subs):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return CaptureResult(tool_calls=[{"name": f"t_{text}", "args": {}}], reply=text)

    serial = await re._run_once(_cases(4), llm=None, full_registry=None, subagents=None,
                                capture_fn=fake_capture, concurrency=1)
    assert peak == 1  # 真串行，不是"信号量=1 的并发"之外还留着重叠

    peak = 0
    parallel = await re._run_once(_cases(4), llm=None, full_registry=None, subagents=None,
                                  capture_fn=fake_capture, concurrency=4)

    # 串行与并发的结果内容等价（同序、同工具）——并发不改变"跑出什么"，只改变"多快跑完"。
    assert [r.input for r in serial] == [r.input for r in parallel]
    assert [r.actual_tools for r in serial] == [r.actual_tools for r in parallel]


@pytest.mark.asyncio
async def test_multiturn_dispatch_still_works_under_concurrency():
    """并发不改变单轮/多轮的分派：多轮走 capture_multiturn_fn 且整段 turns 传入。"""
    import evals.run_evals as re

    seen = {"single": [], "multi": []}

    async def fake_single(text, llm, full, subs):
        seen["single"].append(text)
        return CaptureResult(tool_calls=[{"name": "single", "args": {}}], reply=text)

    async def fake_multi(turns, llm, full, subs):
        seen["multi"].append(list(turns))
        return CaptureResult(tool_calls=[{"name": "multi", "args": {}}], reply=turns[-1])

    cases = [
        {"turns": ["单轮"], "expected_intent": "other"},
        {"turns": ["首轮", "次轮"], "expected_intent": "appointment"},
    ]
    results = await re._run_once(cases, llm=None, full_registry=None, subagents=None,
                                 capture_fn=fake_single, capture_multiturn_fn=fake_multi,
                                 concurrency=2)

    assert seen["single"] == ["单轮"]
    assert seen["multi"] == [["首轮", "次轮"]]
    assert [r.actual_tools[0]["name"] for r in results] == ["single", "multi"]
