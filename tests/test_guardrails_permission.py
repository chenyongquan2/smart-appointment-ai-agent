"""危险操作权限闸门单测（Phase 5）：Tool.dangerous 标记 + ToolRegistry 权限策略。"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from harness.guardrails.permission import Decision, allow_all
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry


class _Args(BaseModel):
    pass


def _make_tool(name: str, *, dangerous: bool, log: list[str]) -> Tool:
    async def handler(args: _Args) -> str:
        log.append(name)
        return f"{name}-done"

    return Tool(name, f"{name} 工具", _Args, handler, dangerous=dangerous)


# --------------------------------------------------------------------------- #
# Tool.dangerous 标记
# --------------------------------------------------------------------------- #
def test_dangerous_flag_defaults_false():
    log: list[str] = []
    assert _make_tool("safe", dangerous=False, log=log).dangerous is False


def test_create_appointment_marked_dangerous():
    from harness.tools.appointment import create_appointment
    from harness.tools.knowledge import search_knowledge

    assert create_appointment.dangerous is True
    assert search_knowledge.dangerous is False  # 只读工具默认非危险


# --------------------------------------------------------------------------- #
# ToolRegistry 权限闸门
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_dangerous_tool_denied_does_not_run_handler():
    log: list[str] = []

    def deny(tool: Tool, args: dict) -> Decision:
        return Decision.denied("需要人工确认")

    reg = ToolRegistry(permission=deny)
    reg.register(_make_tool("create_appointment", dangerous=True, log=log))

    result = await reg.dispatch("create_appointment", {})

    assert log == []  # handler 未被执行
    assert result == {"success": False, "denied": True, "reason": "需要人工确认"}


@pytest.mark.asyncio
async def test_dangerous_tool_allowed_runs_handler():
    log: list[str] = []
    reg = ToolRegistry(permission=allow_all)
    reg.register(_make_tool("create_appointment", dangerous=True, log=log))

    result = await reg.dispatch("create_appointment", {})

    assert log == ["create_appointment"]
    assert result == "create_appointment-done"


@pytest.mark.asyncio
async def test_no_policy_defaults_to_allow():
    log: list[str] = []
    reg = ToolRegistry()  # 未注入策略
    reg.register(_make_tool("create_appointment", dangerous=True, log=log))

    result = await reg.dispatch("create_appointment", {})

    assert log == ["create_appointment"]  # 默认放行，保持既有行为
    assert result == "create_appointment-done"


@pytest.mark.asyncio
async def test_safe_tool_skips_permission_gate():
    log: list[str] = []

    def deny_everything(tool: Tool, args: dict) -> Decision:
        return Decision.denied("拒绝一切")

    reg = ToolRegistry(permission=deny_everything)
    reg.register(_make_tool("search_knowledge", dangerous=False, log=log))

    # 只读工具不经权限闸门，即便策略拒绝一切也照常执行
    result = await reg.dispatch("search_knowledge", {})

    assert log == ["search_knowledge"]
    assert result == "search_knowledge-done"
