"""LLMSummaryMemory 机制单测（add-context-compaction：记忆压缩）。

离线、确定性、不触网：用 duck-typed fake LLM（with_structured_output + ainvoke）、
内存 fake repo、可注入 no-op 退避。只验**机制**（触发/滚动/缓存/降级/可观测/注入位置），
不验摘要文字质量（质量对照见 evals/）。详见 OpenSpec change: add-context-compaction（D9）。
"""

import asyncio

import pytest

from harness.memory.summary import LLMSummaryMemory
from harness.memory.summary_schema import ConversationSummary
from harness.observability.tracer import Tracer


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeChain:
    """with_structured_output 返回的链：记录入参、按预设返回或抛异常。"""

    def __init__(self, result=None, error=None):
        self.result = result if result is not None else ConversationSummary(
            user_constraints=["只要女技师"]
        )
        self.error = error
        self.calls = 0
        self.last_messages = None

    async def ainvoke(self, messages):
        self.calls += 1
        self.last_messages = messages
        if self.error is not None:
            raise self.error
        return self.result


class FakeLLM:
    def __init__(self, chain):
        self._chain = chain

    def with_structured_output(self, schema):
        return self._chain


class FakeConvRepo:
    """单会话：get_turns 返回预设 id-bearing 升序回合。"""

    def __init__(self, rows):
        self._rows = rows

    def get_turns(self, session_id):
        return list(self._rows)


class FakeSumRepo:
    def __init__(self):
        self.store = {}

    def get_summary(self, session_id):
        return self.store.get(session_id)

    def upsert_summary(self, session_id, summary_text, covered_upto):
        self.store[session_id] = {
            "summary_text": summary_text,
            "covered_upto": covered_upto,
        }


class RecordingExporter:
    def __init__(self):
        self.spans = []

    def export(self, span):
        self.spans.append(span)


async def _noop_sleep(_seconds):
    return None


def _rows(n):
    """生成 n 条 id 从 1 起的回合，内容够长以产生非零 token 估算。"""
    out = []
    for i in range(1, n + 1):
        role = "user" if i % 2 == 1 else "assistant"
        out.append({"id": i, "role": role, "content": f"这是第{i}条较长的对话内容，用于测试压缩触发。"})
    return out


def _make(chain, conv_rows, sum_repo, **kw):
    return LLMSummaryMemory(
        llm=FakeLLM(chain),
        conversations_repo=FakeConvRepo(conv_rows),
        summaries_repo=sum_repo,
        window_turns=kw.pop("window_turns", 2),
        retry_sleep=_noop_sleep,
        **kw,
    )


# --------------------------------------------------------------------------- #
# 5.1 未超阈值不触发
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_below_threshold_does_not_trigger():
    chain = FakeChain()
    sum_repo = FakeSumRepo()
    mem = _make(
        chain, _rows(6), sum_repo,
        summary_trigger_tokens=10_000, min_old_turns=100,
    )

    await mem.compact_if_needed("s1")

    assert chain.calls == 0                 # 没调 LLM
    assert sum_repo.get_summary("s1") is None  # 没写缓存


# --------------------------------------------------------------------------- #
# 5.2 超阈值触发：压缩 + 写缓存 + 读侧可取回
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_triggers_and_caches_and_hint_readable():
    chain = FakeChain(ConversationSummary(user_constraints=["只要女技师"]))
    sum_repo = FakeSumRepo()
    mem = _make(chain, _rows(6), sum_repo, summary_trigger_tokens=0, min_old_turns=1)

    await mem.compact_if_needed("s1")

    assert chain.calls == 1
    cached = sum_repo.get_summary("s1")
    assert cached is not None
    assert cached["covered_upto"] == 4      # 窗外 = ids 1..4（window=2），覆盖到末条 4
    hint = mem.get_summary_hint("s1")
    assert "只要女技师" in hint


# --------------------------------------------------------------------------- #
# 5.3 滚动压缩：只并入新回合 + 带入前序摘要
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_rolling_includes_prior_summary_and_only_new_turns():
    chain = FakeChain(ConversationSummary(decisions=["滚动后的摘要"]))
    sum_repo = FakeSumRepo()
    sum_repo.store["s1"] = {"summary_text": "旧摘要内容", "covered_upto": 2}
    mem = _make(chain, _rows(6), sum_repo, summary_trigger_tokens=0, min_old_turns=1)

    await mem.compact_if_needed("s1")

    assert chain.calls == 1
    human = chain.last_messages[-1].content
    # 带入了前序摘要
    assert "已有摘要" in human and "旧摘要内容" in human
    # 只并入未覆盖的新回合（id 3、4），已覆盖的 1、2 不在本次片段里
    assert "第3条" in human and "第4条" in human
    assert "第1条" not in human and "第2条" not in human
    assert sum_repo.get_summary("s1")["covered_upto"] == 4


# --------------------------------------------------------------------------- #
# 5.4 缓存命中：覆盖范围未变不重复调 LLM
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_cache_hit_skips_llm():
    chain = FakeChain()
    sum_repo = FakeSumRepo()
    sum_repo.store["s1"] = {"summary_text": "已覆盖", "covered_upto": 4}  # 已覆盖全部窗外(1..4)
    mem = _make(chain, _rows(6), sum_repo, summary_trigger_tokens=0, min_old_turns=1)

    await mem.compact_if_needed("s1")

    assert chain.calls == 0                  # 命中缓存，不调 LLM
    assert sum_repo.get_summary("s1")["summary_text"] == "已覆盖"  # 未变


# --------------------------------------------------------------------------- #
# 5.5 降级：LLM 失败不崩、不写缓存
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_llm_failure_degrades_without_crash():
    chain = FakeChain(error=asyncio.TimeoutError())
    sum_repo = FakeSumRepo()
    mem = _make(
        chain, _rows(6), sum_repo,
        summary_trigger_tokens=0, min_old_turns=1, llm_max_attempts=2,
    )

    await mem.compact_if_needed("s1")        # 不抛异常

    assert sum_repo.get_summary("s1") is None  # 失败 → 不写缓存
    assert mem.get_summary_hint("s1") == ""    # 读侧退回空（纯窗口）


# --------------------------------------------------------------------------- #
# 5.6 可观测：写侧压缩记 compacted 事件及关键属性
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_tracer_records_compaction_event():
    exporter = RecordingExporter()
    chain = FakeChain()
    sum_repo = FakeSumRepo()
    mem = _make(
        chain, _rows(6), sum_repo,
        summary_trigger_tokens=0, min_old_turns=1, tracer=Tracer(exporter),
    )

    await mem.compact_if_needed("s1")

    events = [e for span in exporter.spans for e in span.events]
    compacted = [e for e in events if e.kind == "compacted"]
    assert len(compacted) == 1
    payload = compacted[0].payload
    for key in ("trigger_reason", "tokens_before", "tokens_after", "covered_upto", "degraded"):
        assert key in payload
    assert payload["degraded"] is False
