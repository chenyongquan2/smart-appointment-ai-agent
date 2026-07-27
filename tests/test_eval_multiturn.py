"""多轮对话用例的评估支持单测（change evals-multiturn-cases）。

覆盖三块，全程离线、不触网、不触碰 services/：
- load_cases：turns 形态加载、input/turns 互斥校验、单轮向后兼容。
- run_and_capture_multiturn：按轮驱动同一 loop、跨轮还原有序工具序列、末轮回复。
- _run_once：按轮长分派（单轮走单轮采集、多轮走多轮采集），EvalResult 正确填充。
"""

from typing import Any, List, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, Field

from evals.agent_capture import CaptureResult, run_and_capture_multiturn
from harness.subagents import SubAgent
from harness.subagents.registry import SubAgentRegistry
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry


# ── 加载层：load_cases 支持多轮 turns ─────────────────────────────────────────
def _write_cases(tmp_path, lines: list[str]):
    p = tmp_path / "cases.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_load_single_turn_normalizes_to_turns(tmp_path):
    """既有单轮 input 用例：归一为单元素 turns（向后兼容）。"""
    from evals.run_evals import load_cases

    path = _write_cases(tmp_path, ['{"input": "你好", "expected_intent": "other"}'])
    cases = load_cases(path)
    assert len(cases) == 1
    assert cases[0]["turns"] == ["你好"]


def test_load_multiturn_turns_list(tmp_path):
    """多轮 turns 用例：原样加载为多元素 turns。"""
    from evals.run_evals import load_cases

    path = _write_cases(
        tmp_path,
        ['{"turns": ["我想约个按摩", "明天下午2点，约李师傅"], "expected_intent": "appointment"}'],
    )
    cases = load_cases(path)
    assert cases[0]["turns"] == ["我想约个按摩", "明天下午2点，约李师傅"]


def test_load_rejects_both_input_and_turns(tmp_path):
    """input 与 turns 并存 → 报错 SystemExit(2)，不静默猜测。"""
    from evals.run_evals import load_cases

    path = _write_cases(
        tmp_path,
        ['{"input": "a", "turns": ["a"], "expected_intent": "other"}'],
    )
    with pytest.raises(SystemExit) as exc:
        load_cases(path)
    assert exc.value.code == 2


def test_load_rejects_neither_input_nor_turns(tmp_path):
    """input 与 turns 皆缺 → 报错 SystemExit(2)。"""
    from evals.run_evals import load_cases

    path = _write_cases(tmp_path, ['{"expected_intent": "other"}'])
    with pytest.raises(SystemExit) as exc:
        load_cases(path)
    assert exc.value.code == 2


def test_load_rejects_empty_turns(tmp_path):
    """turns 为空列表 → 非法。"""
    from evals.run_evals import load_cases

    path = _write_cases(tmp_path, ['{"turns": [], "expected_intent": "other"}'])
    with pytest.raises(SystemExit) as exc:
        load_cases(path)
    assert exc.value.code == 2


# ── 采集层：run_and_capture_multiturn 跨轮还原 ────────────────────────────────
class ScriptedChatModel(BaseChatModel):
    responses: List[AIMessage] = []
    calls: int = 0

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
        idx = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])


def _tool_call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class _Args(BaseModel):
    value: str = Field(default="")


def _fixtures() -> tuple[ToolRegistry, SubAgentRegistry]:
    async def _tool_a(args: _Args) -> str:
        return f"a<{args.value}>"

    async def _tool_b(args: _Args) -> str:
        return f"b<{args.value}>"

    full = ToolRegistry()
    full.register(Tool("tool_a", "工具A", _Args, _tool_a))
    full.register(Tool("tool_b", "工具B", _Args, _tool_b))
    subagents = SubAgentRegistry()
    subagents.register(
        SubAgent(
            name="booker",
            description="会用 tool_a / tool_b",
            tool_names=("tool_a", "tool_b"),
            system_prompt="你会用 tool_a 和 tool_b。",
        )
    )
    return full, subagents


@pytest.mark.asyncio
async def test_multiturn_collects_tools_across_turns():
    """两轮：第1轮触发 tool_a、第2轮触发 tool_b → 跨轮还原出有序 [tool_a, tool_b]，末轮回复为准。"""
    full, subagents = _fixtures()
    # 全局按调用序：
    # 轮1: 主#0 delegate→booker; 子#1 tool_a; 子#2 子复; 主#3 终复[REPLY]
    # 轮2: 主#4 delegate→booker; 子#5 tool_b; 子#6 子复; 主#7 终复[REPLY]
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("delegate", {"subagent": "booker", "task": "用A"}, "c1")]),
            AIMessage(content="", tool_calls=[_tool_call("tool_a", {"value": "x"}, "c2")]),
            AIMessage(content="A 完成。"),
            AIMessage(content="第一轮好了。"),
            AIMessage(content="", tool_calls=[_tool_call("delegate", {"subagent": "booker", "task": "用B"}, "c3")]),
            AIMessage(content="", tool_calls=[_tool_call("tool_b", {"value": "y"}, "c4")]),
            AIMessage(content="B 完成。"),
            AIMessage(content="第二轮也好了。"),
        ]
    )

    cap = await run_and_capture_multiturn(["先用A", "再用B"], llm, full, subagents)

    assert isinstance(cap, CaptureResult)
    names = [c["name"] for c in cap.tool_calls]  # delegate 默认被剔除
    assert names == ["tool_a", "tool_b"]  # 跨轮、按时序
    assert cap.reply == "第二轮也好了。"  # 末轮最终回复


@pytest.mark.asyncio
async def test_single_element_turns_equivalent_to_single_turn():
    """单元素 turns 等价单轮：只采到本轮工具、回复为本轮回复。"""
    full, subagents = _fixtures()
    llm = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[_tool_call("delegate", {"subagent": "booker", "task": "用A"}, "c1")]),
            AIMessage(content="", tool_calls=[_tool_call("tool_a", {"value": "x"}, "c2")]),
            AIMessage(content="A 完成。"),
            AIMessage(content="好了。"),
        ]
    )

    cap = await run_and_capture_multiturn(["只用A"], llm, full, subagents)
    assert [c["name"] for c in cap.tool_calls] == ["tool_a"]
    assert cap.reply == "好了。"


# ── 分派层：_run_once 按轮长选采集路径 ────────────────────────────────────────
@pytest.mark.asyncio
async def test_run_once_dispatches_multiturn_vs_single():
    """_run_once：多轮用例调多轮采集、单轮用例调单轮采集。"""
    import evals.run_evals as re
    from evals.metrics import EvalResult, slots_from_tool_calls

    # 注入模块级占位（正常由 run_baseline 设置）
    re._EvalResult = EvalResult
    re._slots_from_tool_calls = slots_from_tool_calls

    seen = {"single": [], "multi": []}

    async def fake_single(text, llm, full, subs):
        seen["single"].append(text)
        return CaptureResult(tool_calls=[{"name": "tool_a", "args": {}}], reply="单轮回复")

    async def fake_multi(turns, llm, full, subs):
        seen["multi"].append(list(turns))
        return CaptureResult(tool_calls=[{"name": "tool_b", "args": {}}], reply="多轮末轮回复")

    cases = [
        {"turns": ["单轮问句"], "expected_intent": "appointment"},
        {"turns": ["首轮开场", "次轮补全"], "expected_intent": "appointment"},
    ]
    results = await re._run_once(
        cases, llm=None, full_registry=None, subagents=None,
        capture_fn=fake_single, judge_fn=None, capture_multiturn_fn=fake_multi,
    )

    assert seen["single"] == ["单轮问句"]          # 单轮走单轮采集
    assert seen["multi"] == [["首轮开场", "次轮补全"]]  # 多轮走多轮采集，整段传入
    assert results[0].input == "单轮问句"
    assert results[1].input == "首轮开场"           # 多轮 EvalResult.input 取首轮
    assert [c["name"] for c in results[1].actual_tools] == ["tool_b"]


@pytest.mark.asyncio
async def test_run_once_fills_task_success_fields():
    """_run_once 把 CaptureResult.tool_outcomes 填进 actual_tool_outcomes、
    并从用例读 expected_outcome（change evals-task-success-rate）。"""
    import evals.run_evals as re
    from evals.metrics import EvalResult, slots_from_tool_calls

    re._EvalResult = EvalResult
    re._slots_from_tool_calls = slots_from_tool_calls

    async def fake_single(text, llm, full, subs):
        return CaptureResult(
            tool_calls=[{"name": "create_appointment", "args": {}}],
            reply="已为您预约",
            tool_outcomes=[{"name": "create_appointment", "ok": True}],
        )

    cases = [{"turns": ["帮我预约"], "expected_intent": "appointment",
              "expected_outcome": "create_appointment"}]
    results = await re._run_once(
        cases, llm=None, full_registry=None, subagents=None,
        capture_fn=fake_single, judge_fn=None, capture_multiturn_fn=None,
    )
    assert results[0].expected_outcome == "create_appointment"
    assert results[0].actual_tool_outcomes == [{"name": "create_appointment", "ok": True}]
