"""ToolRegistry.subset 单测（Phase 7：任务 2.2）。

子集仅暴露指定工具，其 dispatch 与 schema 导出仅覆盖该工具；含未注册名时报错；
复用既有 Tool 实例（不复制）。全程离线、不触碰 services/。
"""

import pytest
from pydantic import BaseModel, Field

from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry


class _Args(BaseModel):
    value: str = Field(default="")


async def _echo(args: _Args) -> str:
    return f"echo<{args.value}>"


async def _ping(args: _Args) -> str:
    return "pong"


def _full() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(Tool("echo", "回显", _Args, _echo))
    reg.register(Tool("ping", "心跳", _Args, _ping))
    return reg


def test_subset_exposes_only_named_tools():
    sub = _full().subset(["echo"])
    assert sub.names() == ["echo"]


def test_subset_schema_export_covers_only_subset():
    sub = _full().subset(["echo"])
    schema = sub.to_openai_schema()
    assert [t["function"]["name"] for t in schema] == ["echo"]


def test_subset_reuses_same_tool_instance():
    full = _full()
    sub = full.subset(["ping"])
    assert sub.get("ping") is full.get("ping")  # 复用，不复制


@pytest.mark.asyncio
async def test_subset_dispatch_works():
    sub = _full().subset(["echo"])
    assert await sub.dispatch("echo", {"value": "hi"}) == "echo<hi>"


def test_subset_unknown_name_raises():
    with pytest.raises(KeyError):
        _full().subset(["echo", "ghost"])
