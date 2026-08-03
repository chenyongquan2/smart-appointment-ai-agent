"""工具派发文案与失控信号判定的**同源性**守卫（change: fix-trace-triage-blindspots）。

## 这组测试守的是什么

`AgentLoop._dispatch` 把工具超时/异常吞成一句话回灌给模型，而 `trace_signals` 靠**认出
这句话**判定失控信号——这句文案是两个模块间的隐式契约。它已经断过一次：超时支从
`except Exception` 拆出去后，"工具执行**超时**"不匹配"工具执行**失败**"前缀，于是真实群聊
里"连吃三次 60 秒超时、白等 3 分钟"这个坏 case 在 triage 里报 0 个候选。

故这里**不只断言常量相等**（那种测试改文案时会一起改、守不住），而是让真实的
`_dispatch` 跑出真实文案、再喂给真实的 `detect_bad_signals`。文案怎么改都行，
只要两侧同源就过；一旦有人绕开 `harness/tool_outcome.py` 另写一份字面量，这里立刻红。

全程离线：用极小超时值，不真等。
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel

from harness.observability.span import Span, SpanEvent
from harness.observability.trace_signals import (
    TOOL_FAILURE_PREFIX,
    TOOL_TIMEOUT_PREFIX,
    detect_bad_signals,
)
from harness.runtime import AgentLoop
from harness.tool_outcome import tool_failure_message, tool_timeout_message
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry


class _ScriptedModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_ScriptedModel":
        return self

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])


class _Args(BaseModel):
    pass


def _loop_with(tool: Tool, **kwargs: Any) -> AgentLoop:
    registry = ToolRegistry()
    registry.register(tool)
    return AgentLoop(llm=_ScriptedModel(), registry=registry, **kwargs)


def _slow_tool(name: str = "slow") -> Tool:
    async def _handler(args: _Args) -> str:
        await asyncio.sleep(5.0)  # 有 await 点 → wait_for 能真正中断
        return "不该到这里"

    return Tool(name=name, description="慢工具", args_schema=_Args, handler=_handler)


def _boom_tool(name: str = "boom") -> Tool:
    async def _handler(args: _Args) -> str:
        raise RuntimeError("炸了")

    return Tool(name=name, description="会抛的工具", args_schema=_Args, handler=_handler)


def _step_with_observation(result: str) -> Span:
    """把一句 observation 包成一个 step span（终态未产出 → 保留 tool_call 事件）。"""
    span = Span(trace_id="t", span_id="s1", parent_id=None, name="step", start=0.0, end=1.0)
    span.events.append(SpanEvent("tool_call", {"name": "slow", "args": {}}))
    span.events.append(SpanEvent("observation", {"name": "slow", "result": result}))
    return span


# ── 真实 _dispatch 的文案能被真实判定认出（本组的核心）─────────────────────
@pytest.mark.asyncio
async def test_real_dispatch_timeout_text_is_detected_as_signal():
    """★ 防漂移主守卫：真实超时文案 → 真实信号判定，必须命中 tool_timeout。

    这条红了通常意味着有人改了超时文案但没走 harness/tool_outcome.py。
    """
    loop = _loop_with(_slow_tool(), tool_timeout=0.01)

    result = await loop._dispatch({"name": "slow", "args": {}, "id": "c1"})

    signals = detect_bad_signals([_step_with_observation(str(result))])
    assert "tool_timeout" in signals, (
        f"真实 _dispatch 的超时文案未被 detect_bad_signals 认出。"
        f"实际文案={result!r}；判定用的前缀={TOOL_TIMEOUT_PREFIX!r}。"
        f"文案与判定必须同源于 harness/tool_outcome.py。"
    )


@pytest.mark.asyncio
async def test_real_dispatch_failure_text_is_detected_as_signal():
    """异常路径同理：真实失败文案必须命中 tool_failure。"""
    loop = _loop_with(_boom_tool())

    result = await loop._dispatch({"name": "boom", "args": {}, "id": "c1"})

    signals = detect_bad_signals([_step_with_observation(str(result))])
    assert "tool_failure" in signals, (
        f"真实 _dispatch 的失败文案未被认出。实际文案={result!r}；"
        f"判定用的前缀={TOOL_FAILURE_PREFIX!r}。"
    )


@pytest.mark.asyncio
async def test_timeout_and_failure_are_not_confused():
    """超时与失败必须落到不同标签——补救动作不同（收窄 vs 改参），混起来候选就没法用了。"""
    timeout_result = await _loop_with(_slow_tool(), tool_timeout=0.01)._dispatch(
        {"name": "slow", "args": {}, "id": "c1"}
    )
    failure_result = await _loop_with(_boom_tool())._dispatch(
        {"name": "boom", "args": {}, "id": "c1"}
    )

    timeout_signals = detect_bad_signals([_step_with_observation(str(timeout_result))])
    failure_signals = detect_bad_signals([_step_with_observation(str(failure_result))])

    assert "tool_timeout" in timeout_signals and "tool_failure" not in timeout_signals
    assert "tool_failure" in failure_signals and "tool_timeout" not in failure_signals


# ── 格式化函数与前缀常量同源 ────────────────────────────────────────────────
def test_formatters_start_with_their_prefixes():
    """前缀常量与格式化函数产出必须一致——两者分离就是当初漂移的根因。"""
    assert tool_timeout_message("t", 60).startswith(TOOL_TIMEOUT_PREFIX)
    assert tool_failure_message("t", ValueError("x")).startswith(TOOL_FAILURE_PREFIX)


def test_timeout_message_keeps_actionable_wording():
    """超时文案要让模型知道「别指望系统自动重发」，并带上工具名与秒数。"""
    msg = tool_timeout_message("vlog_query", 60)
    assert "vlog_query" in msg and "60" in msg and "不会重试" in msg


def test_tool_outcome_stays_dependency_free():
    """本模块 MUST 保持零重依赖，否则 import 期成环的风险会被搬回来（见其 docstring）。

    ``harness/runtime/__init__.py`` 导入 ``AgentLoop`` → ``AgentLoop`` 导入
    ``harness.observability.tracer``；若 tool_outcome 反向 import 这两层即构成循环。
    """
    import ast
    import inspect

    import harness.tool_outcome as mod

    # 用 AST 查**真实的 import 语句**，而不是扫源码字符串——后者会被本模块自己
    # docstring 里"不 import langchain/observability/runtime"这句话误伤
    # （与 tests/test_domain_loading.py 用 AST 剔除 docstring 是同一个理由）。
    tree = ast.parse(inspect.getsource(mod))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    forbidden = ("harness.runtime", "harness.observability", "langchain")
    offenders = [m for m in imported if any(m.startswith(f) for f in forbidden)]
    assert not offenders, (
        f"harness/tool_outcome.py MUST NOT 依赖 {offenders}——会把 import 期成环的风险搬回来。"
    )
