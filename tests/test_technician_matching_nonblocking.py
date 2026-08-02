"""技师专长相似度匹配的非阻塞与并发（change: fix-technician-embedding-blocking）。

守的是三件**互相独立**的事，任一失守都会以不同方式伤到线上：

1. **不阻塞**：向量化挂起期间事件循环仍能推进。失守 → 同进程所有协程（含飞书长连接的
   收包与心跳）一并停摆，整个服务假死。
2. **并发**：N 个候选一轮打完，而非串行 N 轮。失守 → 延迟 ``N × RTT``，很容易撞上
   agent loop 的工具超时被整体掐断，**功能上等价于失败**（所以这不只是性能问题）。
3. **顺序**：并发不改变相似度排序。失守 → 匹配结果悄悄漂移，且没有任何报错。

历史：这条链曾经就是同步的（``async handler`` → ``TechnicianFinder`` → 同步
``embed_input``），与 ``fix-embedding-timeout-blocking`` 修掉的知识库那条是同一个缺陷，
当时漏了。本文件是它的回归守卫，角色对应已删除的
``test_knowledge_search_does_not_block_the_loop``。

``@pytest.mark.timeout`` 不是可选装饰：把实现改回同步后，这些用例**不会失败而会挂死**
——事件循环被冻住，连它们自己的 ``asyncio.wait_for`` 定时器都跑不了，任何基于 asyncio
的超时都救不了自己。``pytest-timeout`` 走线程/信号，能把「挂死」变成「明确失败」。

全程离线：注入 fake embeddings，不触网。
"""

from __future__ import annotations

import asyncio
import hashlib
import time

import pytest

import services.text_embedding as te


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
def _deterministic_vector(text: str) -> list[float]:
    """文本 → 固定向量。同一文本恒得同一向量，故排序断言可以写死。"""
    digest = hashlib.md5(text.encode()).digest()
    return [b / 255.0 for b in digest[:8]]


class HangingEmbeddings:
    """永不返回的嵌入实现——模拟挂死的 HTTP 请求。"""

    def __init__(self) -> None:
        self.sync_calls = 0
        self.async_calls = 0

    def embed_query(self, text: str) -> list:
        self.sync_calls += 1
        time.sleep(3600)  # 同步阻塞：无 await 点，取消不掉
        return [0.0]

    async def aembed_query(self, text: str) -> list:
        self.async_calls += 1
        await asyncio.sleep(3600)  # 异步挂起：可被取消
        return [0.0]


class SlowEmbeddings:
    """每次调用固定耗时的嵌入实现——用来区分「并发」与「串行」。"""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.calls = 0
        self.max_in_flight = 0
        self._in_flight = 0

    async def aembed_query(self, text: str) -> list:
        self.calls += 1
        self._in_flight += 1
        # 记录并发峰值：串行实现下这个值恒为 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            await asyncio.sleep(self.delay)
            return _deterministic_vector(text)
        finally:
            self._in_flight -= 1


class DeterministicEmbeddings:
    """立即返回固定向量——用于排序断言。"""

    async def aembed_query(self, text: str) -> list:
        return _deterministic_vector(text)


CANDIDATES = ["力气大 深层按压", "手法轻柔 放松", "肩颈专精", "足底反射区", "孕产妇护理"]


# --------------------------------------------------------------------------- #
# ① ★ 不阻塞（本变更的核心断言）
# --------------------------------------------------------------------------- #
@pytest.mark.timeout(20)
@pytest.mark.asyncio
async def test_matching_does_not_block_the_event_loop(monkeypatch):
    """★ 候选向量化挂着的同时，别的协程必须仍被按时调度。

    实现若退回同步版，这条不会失败而会挂死（见模块 docstring）。
    """
    fake = HangingEmbeddings()
    monkeypatch.setattr(te, "create_embedding_model", lambda **kw: fake)

    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.01)
            ticks += 1

    matching = asyncio.ensure_future(te.afind_best_match_indices("力气大", CANDIDATES))
    await asyncio.wait_for(heartbeat(), timeout=2.0)
    matching.cancel()

    assert ticks == 5                    # 心跳跑满 → 循环没被占住
    assert fake.async_calls == len(CANDIDATES) + 1   # 走的是异步路径（候选 + 查询）
    assert fake.sync_calls == 0                      # 一次同步阻塞调用都没有


@pytest.mark.timeout(20)
@pytest.mark.asyncio
async def test_technician_finder_does_not_block_the_event_loop(monkeypatch):
    """把范围推到真实调用链：``TechnicianFinder`` 这一层也不得冻住循环。

    与上一条的分工：上一条守底层函数，这条守「调用点确实改成了 await 异步版」——
    若 finder 里某处漏改回同步调用，心跳会停。
    """
    fake = HangingEmbeddings()
    monkeypatch.setattr(te, "create_embedding_model", lambda **kw: fake)

    from services.technician_matching import TechnicianFinder

    techs = [{"id": i, "name": f"技师{i}", "strength": s} for i, s in enumerate(CANDIDATES)]
    finder = TechnicianFinder()

    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.01)
            ticks += 1

    filtering = asyncio.ensure_future(
        finder.filter_technicians_by_preference(techs, "力气大")
    )
    await asyncio.wait_for(heartbeat(), timeout=2.0)
    filtering.cancel()

    assert ticks == 5
    assert fake.sync_calls == 0


# --------------------------------------------------------------------------- #
# ② 并发而非串行
# --------------------------------------------------------------------------- #
@pytest.mark.timeout(20)
@pytest.mark.asyncio
async def test_candidates_are_embedded_concurrently(monkeypatch):
    """N 个候选必须一轮打完。

    只断言「不阻塞」是不够的：``for c in candidates: await aembed_input(c)`` 同样不冻
    循环，却把延迟放大到 N 倍。这条用**并发峰值**和**总耗时**两个角度一起卡死它。
    """
    fake = SlowEmbeddings(delay=0.05)
    monkeypatch.setattr(te, "create_embedding_model", lambda **kw: fake)

    started = time.monotonic()
    await te.afind_best_match_indices("力气大", CANDIDATES)
    elapsed = time.monotonic() - started

    expected_calls = len(CANDIDATES) + 1     # 候选 + 查询本身
    assert fake.calls == expected_calls
    # 并发峰值应达到全部请求数；串行实现下恒为 1
    assert fake.max_in_flight == expected_calls
    # 串行需 6×0.05=0.3s；并发约 0.05s。取 0.15s 作阈值，给 CI 抖动留足余量
    assert elapsed < 0.15, f"耗时 {elapsed:.3f}s，疑似串行"


# --------------------------------------------------------------------------- #
# ③ 并发不改变排序结果
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ordering_is_stable_and_matches_candidate_indices(monkeypatch):
    """给定确定性向量，返回的下标序列必须稳定。

    ``asyncio.gather`` 按**传入顺序**而非完成顺序返回，这是下标对应关系成立的前提。
    若有人改成 ``asyncio.as_completed`` 之类按完成顺序收集，这条会挂。
    """
    monkeypatch.setattr(te, "create_embedding_model", lambda **kw: DeterministicEmbeddings())

    first = await te.afind_best_match_indices("力气大", CANDIDATES)
    second = await te.afind_best_match_indices("力气大", CANDIDATES)

    assert first == second                          # 可重复
    assert sorted(first) == list(range(len(CANDIDATES)))  # 是候选下标的一个排列，不丢不重


@pytest.mark.asyncio
async def test_乱序返回也不影响下标对应(monkeypatch):
    """完成顺序被打乱时，结果仍按候选下标对应。

    让每个候选的耗时与其内容相关（后面的先返回），若实现按完成顺序收集向量，
    向量就会和候选错位、排序随之出错。
    """
    order = {text: (len(CANDIDATES) - i) * 0.01 for i, text in enumerate(CANDIDATES)}

    class ShuffledCompletion:
        async def aembed_query(self, text: str) -> list:
            await asyncio.sleep(order.get(text, 0.0))
            return _deterministic_vector(text)

    monkeypatch.setattr(te, "create_embedding_model", lambda **kw: ShuffledCompletion())
    shuffled = await te.afind_best_match_indices("力气大", CANDIDATES)

    monkeypatch.setattr(te, "create_embedding_model", lambda **kw: DeterministicEmbeddings())
    baseline = await te.afind_best_match_indices("力气大", CANDIDATES)

    assert shuffled == baseline


# --------------------------------------------------------------------------- #
# ④ 边界
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_empty_candidates_makes_no_request(monkeypatch):
    """空候选直接返回，且**一个请求都不发**（别为没有候选的情形付一次网络往返）。"""
    fake = SlowEmbeddings()
    monkeypatch.setattr(te, "create_embedding_model", lambda **kw: fake)

    assert await te.afind_best_match_indices("力气大", []) == []
    assert fake.calls == 0


@pytest.mark.asyncio
async def test_no_preference_skips_embedding_entirely(monkeypatch):
    """无偏好时 finder 应短路返回，不做任何向量化。

    多数用例不带偏好，这条短路直接决定了它们要不要付一次网络往返。
    """
    fake = SlowEmbeddings()
    monkeypatch.setattr(te, "create_embedding_model", lambda **kw: fake)

    from services.technician_matching import TechnicianFinder

    techs = [{"id": i, "name": f"技师{i}", "strength": s} for i, s in enumerate(CANDIDATES)]
    finder = TechnicianFinder()

    assert await finder.filter_technicians_by_preference(techs, "无") is techs
    assert await finder.filter_technicians_by_preference(techs, "") is techs
    assert fake.calls == 0
