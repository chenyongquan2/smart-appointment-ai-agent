"""LLM-judge（改造 4）的离线确定性单测。

覆盖 judge 调用层（注入 fake judge，不触网）、回复质量聚合、judge-人工校准（κ）、
未校准标注，以及 run_and_capture surface 最终回复。全程离线、不触网。
"""

import math
from typing import Any, List, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field

from evals.judge import JudgeVerdict, judge_response
from evals.metrics import EvalResult, response_quality, judge_human_agreement
from evals.agent_capture import run_and_capture
from harness.subagents import SubAgent
from harness.subagents.registry import SubAgentRegistry
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry


# --------------------------------------------------------------------------- #
# fake judge：with_structured_output 返回一个直接吐预设裁决的 runnable（不触网）。
# --------------------------------------------------------------------------- #
class _FakeJudgeLLM:
    def __init__(self, verdict: JudgeVerdict, raise_exc: bool = False):
        self._verdict = verdict
        self._raise = raise_exc

    def with_structured_output(self, schema: Any):
        if self._raise:
            def _boom(_inp):
                raise RuntimeError("judge boom")
            return RunnableLambda(_boom)
        v = self._verdict
        return RunnableLambda(lambda _inp: v)


@pytest.mark.asyncio
async def test_judge_response_parses_verdict():
    fake = _FakeJudgeLLM(JudgeVerdict(reason="相关且正确", passed=True))
    verdict = await judge_response("推拿多少钱", "推拿 100 元/小时。", fake)
    assert verdict.passed is True
    assert "相关" in verdict.reason


@pytest.mark.asyncio
async def test_judge_response_degrades_on_error():
    # judge 调用异常 → 安全降级为 passed=False（不崩整轮，如实记不通过）。
    fake = _FakeJudgeLLM(JudgeVerdict(reason="x", passed=True), raise_exc=True)
    verdict = await judge_response("q", "a", fake)
    assert verdict.passed is False
    assert "异常" in verdict.reason


# --------------------------------------------------------------------------- #
# response_quality 聚合
# --------------------------------------------------------------------------- #
def test_response_quality_pass_rate_and_uncalibrated_note():
    results = [
        EvalResult("a", "query", judge_passed=True),
        EvalResult("b", "query", judge_passed=True),
        EvalResult("c", "query", judge_passed=False),
    ]
    m = response_quality(results)  # 默认 calibrated=False
    assert (m.numerator, m.denominator) == (2, 3)
    assert math.isclose(m.value, 2 / 3, rel_tol=1e-9)
    assert "未校准" in m.note  # 未校准显式标注


def test_response_quality_calibrated_no_note():
    results = [EvalResult("a", "query", judge_passed=True)]
    m = response_quality(results, calibrated=True)
    assert m.note == ""


def test_response_quality_na_when_not_judged():
    results = [EvalResult("a", "query")]  # 未开 judge → judge_passed=None
    m = response_quality(results)
    assert m.na and m.value is None


# --------------------------------------------------------------------------- #
# judge_human_agreement（Cohen's κ）
# --------------------------------------------------------------------------- #
def test_kappa_perfect_agreement():
    out = judge_human_agreement([True, True, False, False], [True, True, False, False])
    assert out["agreement"] == 1.0
    assert math.isclose(out["kappa"], 1.0, rel_tol=1e-9)


def test_kappa_total_disagreement_negative():
    out = judge_human_agreement([True, False, True, False], [False, True, False, True])
    assert out["agreement"] == 0.0
    assert out["kappa"] < 0  # 比随机还差 → 负 κ


def test_kappa_length_mismatch_raises():
    with pytest.raises(ValueError):
        judge_human_agreement([True], [True, False])


def test_kappa_empty_raises():
    with pytest.raises(ValueError):
        judge_human_agreement([], [])


# --------------------------------------------------------------------------- #
# run_and_capture surface 最终回复
# --------------------------------------------------------------------------- #
class _ScriptedChatModel(BaseChatModel):
    responses: List[AIMessage] = []
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_ScriptedChatModel":
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        idx = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])


@pytest.mark.asyncio
async def test_run_and_capture_surfaces_reply():
    full = ToolRegistry()
    subagents = SubAgentRegistry()  # 空：主 agent 直接回复，不派生
    llm = _ScriptedChatModel(responses=[AIMessage(content="您好，有什么可以帮您？")])

    result = await run_and_capture("你好", llm, full, subagents)

    assert result.reply == "您好，有什么可以帮您？"
    assert result.tool_calls == []  # 没调工具
