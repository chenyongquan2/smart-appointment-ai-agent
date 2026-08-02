"""知识库检索端口与 search_knowledge 工具（change: remove-local-rag）。

本地 RAG 删除后，工具依赖的是 ``services/knowledge_search.py`` 的可替换端口。
这里守四件事：

1. **未接入时以「失败」收场**——经 agent loop 的 ``_dispatch`` 变成
   ``工具执行失败（search_knowledge）：…``，loop 不崩。刻意不是空列表、也不是
   「看起来成功」的结构化结果，理由见 change 的 design D2（前者让模型编造答案，
   后者让 `任务成功率` 把「根本没检索到」记成业务终态达成）。
2. **注入实现后照常工作**——工具把已校验参数原样转交端口。
3. **工具契约没被改动**——name / description / args_schema / dangerous 全都不变，
   这是「上层零改动」（registry、子 Agent、评估用例标注）的前提。
4. **离线确定性**——注入 fake 后同一输入两次调用结果一致，不触网。
"""

from __future__ import annotations

from typing import Any, List, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import services.knowledge_search as ks
from harness.observability.trace_signals import TOOL_FAILURE_PREFIX
from harness.runtime import AgentLoop
from harness.tools.knowledge import search_knowledge
from harness.tools.registry import ToolRegistry
from harness.tools.schemas import SearchKnowledgeArgs


class ScriptedChatModel(BaseChatModel):
    """按预设序列返回 AIMessage；本文件直接测 _dispatch，LLM 不参与断言。"""

    responses: List[AIMessage] = []

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self.responses[-1])])


@pytest.fixture(autouse=True)
def _restore_port():
    """每条用例后还原端口，避免注入串味到其他测试文件。"""
    previous = ks.get_knowledge_search()
    yield
    ks.set_knowledge_search(previous)


class FakeKnowledgeSearch:
    """返回固定文档的假端口——评估/测试的离线确定性就靠这个形状。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, Optional[str]]] = []

    async def search(
        self, query: str, top_k: int = 3, category: Optional[str] = None
    ) -> list[dict[str, Any]]:
        self.calls.append((query, top_k, category))
        return [{"content": "营业时间 9:00-22:00", "category": "营业时间", "score": 0.93}]


def _loop_with_search_knowledge() -> AgentLoop:
    registry = ToolRegistry()
    registry.register(search_knowledge)
    # LLM 不参与本组断言（直接测 _dispatch），给个最简脚本即可。
    llm = ScriptedChatModel(responses=[AIMessage(content="done")])
    return AgentLoop(llm=llm, registry=registry)


# --------------------------------------------------------------------------- #
# ① 未接入：明确失败，loop 不崩
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_not_configured_surfaces_as_tool_failure_not_a_crash():
    """★ 本变更的核心断言。

    缺省端口抛 KnowledgeBackendNotConfigured，_dispatch 把它吞成以
    TOOL_FAILURE_PREFIX 开头的字符串回灌——于是 evals 的 `任务成功率` 判定为未达成
    （诚实），trace_signals 的坏信号点亮（可观测），而 agent loop 继续往下走（不崩）。
    """
    ks.set_knowledge_search(None)  # 显式回到「未接入」缺省态
    loop = _loop_with_search_knowledge()

    result = await loop._dispatch(
        {"name": "search_knowledge", "args": {"query": "营业时间"}, "id": "c1"}
    )

    assert isinstance(result, str)
    assert result.startswith(TOOL_FAILURE_PREFIX)
    assert "知识库尚未接入" in result


@pytest.mark.asyncio
async def test_not_configured_message_tells_the_model_not_to_make_things_up():
    """回灌文本是**给模型的行为指令**，不只是给人看的日志。

    少了「不要凭猜测回答」这句，模型很容易拿训练知识现编价格与营业时间——那正是
    删掉本地 RAG 后最现实的失效模式。
    """
    ks.set_knowledge_search(None)
    loop = _loop_with_search_knowledge()

    result = await loop._dispatch(
        {"name": "search_knowledge", "args": {"query": "全身推拿多少钱"}, "id": "c1"}
    )

    assert "如实告知" in result
    assert "不要凭猜测" in result


@pytest.mark.asyncio
async def test_not_configured_never_returns_an_empty_list():
    """直接调工具（绕过 _dispatch）时是抛异常，绝不是空列表。

    空列表会被模型读成「查过了、库里没有这条」——比明确失败糟得多。
    """
    ks.set_knowledge_search(None)

    with pytest.raises(ks.KnowledgeBackendNotConfigured):
        await search_knowledge.run({"query": "营业时间"})


# --------------------------------------------------------------------------- #
# ② 注入实现后照常工作
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_injected_port_receives_validated_args():
    fake = FakeKnowledgeSearch()
    ks.set_knowledge_search(fake)

    result = await search_knowledge.run({"query": "营业时间", "top_k": 2, "category": "营业时间"})

    assert fake.calls == [("营业时间", 2, "营业时间")]
    assert result == [{"content": "营业时间 9:00-22:00", "category": "营业时间", "score": 0.93}]


@pytest.mark.asyncio
async def test_injection_takes_effect_immediately():
    """handler 每次调用都重新解析端口，故运行中注入能即时生效（无需重建工具/registry）。"""
    ks.set_knowledge_search(None)
    with pytest.raises(ks.KnowledgeBackendNotConfigured):
        await search_knowledge.run({"query": "地址"})

    ks.set_knowledge_search(FakeKnowledgeSearch())
    assert await search_knowledge.run({"query": "地址"})


@pytest.mark.asyncio
async def test_set_returns_previous_for_restore():
    first, second = FakeKnowledgeSearch(), FakeKnowledgeSearch()
    ks.set_knowledge_search(first)

    previous = ks.set_knowledge_search(second)

    assert previous is first
    assert ks.get_knowledge_search() is second


# --------------------------------------------------------------------------- #
# ③ 工具契约未被改动（上层零改动的前提）
# --------------------------------------------------------------------------- #
def test_tool_contract_is_unchanged():
    """换实现不得改契约——一旦这条红了，registry/子 Agent/评估用例就都得跟着改。"""
    assert search_knowledge.name == "search_knowledge"
    assert search_knowledge.args_schema is SearchKnowledgeArgs
    assert search_knowledge.dangerous is False          # 只读检索，不走权限闸门
    assert "知识库" in search_knowledge.description      # 给模型的说明书仍在讲知识库检索


# --------------------------------------------------------------------------- #
# ④ 离线确定性（评估要的正是这个）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_injected_port_is_deterministic():
    ks.set_knowledge_search(FakeKnowledgeSearch())

    first = await search_knowledge.run({"query": "营业时间"})
    second = await search_knowledge.run({"query": "营业时间"})

    assert first == second
