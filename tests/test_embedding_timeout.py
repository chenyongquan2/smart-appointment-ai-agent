"""嵌入调用的超时与非阻塞（change: fix-embedding-timeout-blocking）。

守的是**两个不同的缺陷**，故断言也分成两组：

1. **有超时**：请求永不返回时，调用必须在上限内以失败收场，不无限期挂起。
   （原缺陷：`embed_input` 的 `timeout` 参数从未使用，客户端也不带超时，落到 openai
   默认 600 秒。）
2. **不阻塞**：等待期间事件循环必须仍能推进。
   （原缺陷：`embed_query` 是同步阻塞调用却被 `async` 方法直接调用，占住整个循环——
   连 `asyncio.wait_for` 的定时器回调都跑不了，于是任何外层超时都形同不存在。）

第 2 组是本变更真正的核心：只满足第 1 组的实现（客户端带超时但调用仍同步）在超时那
段时间里依然会把整个服务冻住。两组必须分别守。

全程离线：注入永不返回的 fake，不触网、不产生分钟级真实等待。

📌 **真实调用链的覆盖在哪**：本文件只在 ``aembed_input`` 这一层守「不阻塞」。原有的
``test_knowledge_search_does_not_block_the_loop``（把断言推到真实调用链）随
``KnowledgeService`` 删除（change: remove-local-rag），其角色现由
``tests/test_technician_matching_nonblocking.py`` 承担——技师专长匹配那条链曾
**真的违反过**本文件第 2 组守的约束（async handler → ``TechnicianFinder`` →
同步 ``embed_input``），已于 change ``fix-technician-embedding-blocking`` 修复并补守。
接入远程 RAG client 时须按 ``guardrails`` 需求为它补回同款用例。

两条"不阻塞"用例带 ``@pytest.mark.timeout``，理由值得记一笔：把修复改回同步实现后，
这些用例**不会失败而会挂死**——事件循环被冻住，连它们自己的 ``asyncio.wait_for``
定时器都跑不了。任何基于 asyncio 的超时在这种情形下都失效，测试救不了自己。
``pytest-timeout`` 走线程/信号、不依赖事件循环，故能把「挂死」变成「明确失败」。
这已用变异验证过：临时把 ``aembed_input`` 退回 ``embed_query`` 后，两条用例确实挂死。
"""

from __future__ import annotations

import asyncio
import time

import pytest

import services.text_embedding as te
from config.model_provider import (
    DEFAULT_EMBEDDING_TIMEOUT,
    create_embedding_model,
    resolve_embedding_timeout,
)


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
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


class RecordingEmbeddings:
    """记录调用并立即返回，用于验证参数透传。"""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_query(self, text: str) -> list:
        self.queries.append(text)
        return [1.0, 2.0]

    async def aembed_query(self, text: str) -> list:
        self.queries.append(text)
        return [1.0, 2.0]


# --------------------------------------------------------------------------- #
# ① 客户端确实带上了超时（守「有超时」的地基）
# --------------------------------------------------------------------------- #
def test_client_carries_the_configured_timeout():
    """不触网，只看实例属性。

    注意断言 `request_timeout` 而非 `timeout`——后者是 LangChain 的**别名**，
    实例上并不存在同名属性。这个坑值得测试记一笔。
    """
    model = create_embedding_model()

    assert model.request_timeout == DEFAULT_EMBEDDING_TIMEOUT


def test_explicit_timeout_overrides_default():
    assert create_embedding_model(timeout=7).request_timeout == 7.0


def test_timeout_is_never_the_minutes_scale_default():
    """回归守卫：600 秒对一次无生成的短请求等于没有上限，绝不能回退到它。"""
    assert create_embedding_model().request_timeout < 60


@pytest.mark.parametrize("raw,expected", [
    (None, DEFAULT_EMBEDDING_TIMEOUT),
    ("35", 35.0),
    ("12.5", 12.5),
    ("", DEFAULT_EMBEDDING_TIMEOUT),          # 空值按未设置处理
    ("不是数字", DEFAULT_EMBEDDING_TIMEOUT),   # 配置写错不该让服务起不来
])
def test_timeout_resolution_from_env(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("EMBEDDING_TIMEOUT_SECONDS", raising=False)
    else:
        monkeypatch.setenv("EMBEDDING_TIMEOUT_SECONDS", raw)

    assert resolve_embedding_timeout() == expected


def test_explicit_argument_wins_over_env(monkeypatch):
    monkeypatch.setenv("EMBEDDING_TIMEOUT_SECONDS", "99")

    assert resolve_embedding_timeout(5) == 5.0


# --------------------------------------------------------------------------- #
# ② 挂起的调用可被掐断（守「有超时」）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_hanging_async_call_can_be_cancelled(monkeypatch):
    """异步路径的调用可被取消——这是客户端超时之外的第二道保险。

    对照原缺陷：同步 `embed_query` 在这里是取消不掉的（见下面那条 xfail 式的边界用例）。
    """
    fake = HangingEmbeddings()
    monkeypatch.setattr(te, "create_embedding_model", lambda **kw: fake)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(te.aembed_input("你好"), timeout=0.05)

    assert fake.async_calls == 1


@pytest.mark.asyncio
async def test_async_path_passes_timeout_through(monkeypatch):
    captured: dict = {}

    def _factory(**kwargs):
        captured.update(kwargs)
        return RecordingEmbeddings()

    monkeypatch.setattr(te, "create_embedding_model", _factory)

    await te.aembed_input("你好", timeout=3)

    assert captured["timeout"] == 3


def test_sync_path_passes_timeout_through(monkeypatch):
    """同步版的 `timeout` 也必须真正透传——它曾经是个从不生效的装饰参数。"""
    captured: dict = {}

    def _factory(**kwargs):
        captured.update(kwargs)
        return RecordingEmbeddings()

    monkeypatch.setattr(te, "create_embedding_model", _factory)

    te.embed_input("你好", timeout=9)

    assert captured["timeout"] == 9


# --------------------------------------------------------------------------- #
# ③ ★ 等待期间事件循环仍能推进（守「不阻塞」——本变更的核心断言）
# --------------------------------------------------------------------------- #
@pytest.mark.timeout(20)
@pytest.mark.asyncio
async def test_event_loop_keeps_running_while_embedding_waits(monkeypatch):
    """★ 这条是本变更的核心。

    嵌入调用挂着的同时，另一个协程必须仍被按时调度。若实现退回同步阻塞版，
    这条会超时失败——因为整个事件循环被冻住，连 `wait_for` 的定时器都跑不了。
    """
    fake = HangingEmbeddings()
    monkeypatch.setattr(te, "create_embedding_model", lambda **kw: fake)

    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.01)
            ticks += 1

    embedding = asyncio.ensure_future(te.aembed_input("你好"))
    await asyncio.wait_for(heartbeat(), timeout=2.0)
    embedding.cancel()

    assert ticks == 5   # 心跳全跑完了 → 循环没被嵌入调用占住
    assert fake.async_calls == 1


# --------------------------------------------------------------------------- #
# ④ 边界记录：同步版确实取消不掉（这正是不能在 async 里用它的原因）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_sync_version_is_not_cancellable_by_design(monkeypatch):
    """把「为什么必须有异步版」钉成可执行的证据。

    同步 `embed_input` 内部无 await 点，`wait_for` 掐不断它——这不是 bug，是
    asyncio 取消机制的固有边界。本用例用一个短的同步 sleep 演示：即便外层只给 10ms，
    调用仍会完整跑完。故 `async` 上下文必须用 `aembed_input`。
    """
    class BrieflyBlocking:
        def __init__(self) -> None:
            self.finished = False

        def embed_query(self, text: str) -> list:
            time.sleep(0.05)      # 同步阻塞，无 await 点
            self.finished = True
            return [0.0]

    fake = BrieflyBlocking()
    monkeypatch.setattr(te, "create_embedding_model", lambda **kw: fake)

    started = time.monotonic()
    try:
        await asyncio.wait_for(asyncio.to_thread(te.embed_input, "你好"), timeout=0.01)
    except asyncio.TimeoutError:
        pass
    # 即使外层已超时返回，同步调用仍在后台跑到自己结束——线程与连接都还占着。
    await asyncio.sleep(0.1)

    assert fake.finished is True
    assert time.monotonic() - started >= 0.05
