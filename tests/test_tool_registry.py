"""ToolRegistry 单测（Phase 2）：注册/分发/导出 schema。"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry
from tests._domain_helpers import build_default_registry


class _EchoArgs(BaseModel):
    value: str = Field(description="任意字符串")
    count: int = Field(default=1, description="重复次数")


def _make_echo_tool(name: str = "echo") -> Tool:
    async def handler(args: _EchoArgs):
        return args.value * args.count

    return Tool(
        name=name,
        description="回声工具",
        args_schema=_EchoArgs,
        handler=handler,
    )


def test_register_and_get():
    reg = ToolRegistry()
    tool = _make_echo_tool()
    reg.register(tool)
    assert reg.get("echo") is tool
    assert reg.names() == ["echo"]


def test_register_duplicate_raises():
    reg = ToolRegistry()
    reg.register(_make_echo_tool())
    with pytest.raises(ValueError):
        reg.register(_make_echo_tool())


def test_get_unknown_raises():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.get("missing")


async def test_dispatch_validates_and_runs():
    reg = ToolRegistry()
    reg.register(_make_echo_tool())
    result = await reg.dispatch("echo", {"value": "ab", "count": 3})
    assert result == "ababab"


async def test_dispatch_unknown_raises():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        await reg.dispatch("missing", {})


async def test_dispatch_invalid_args_raises():
    from pydantic import ValidationError

    reg = ToolRegistry()
    reg.register(_make_echo_tool())
    with pytest.raises(ValidationError):
        await reg.dispatch("echo", {})  # 缺 value


def test_openai_schema_shape():
    reg = ToolRegistry()
    reg.register(_make_echo_tool())
    schema = reg.to_openai_schema()
    assert len(schema) == 1
    entry = schema[0]
    assert entry["type"] == "function"
    fn = entry["function"]
    assert fn["name"] == "echo"
    assert fn["description"] == "回声工具"
    # 参数源于 Pydantic 模型
    assert "value" in fn["parameters"]["properties"]
    assert "count" in fn["parameters"]["properties"]


def test_anthropic_schema_shape():
    reg = ToolRegistry()
    reg.register(_make_echo_tool())
    schema = reg.to_anthropic_schema()
    assert len(schema) == 1
    entry = schema[0]
    assert entry["name"] == "echo"
    assert entry["description"] == "回声工具"
    assert "value" in entry["input_schema"]["properties"]


def test_schema_reflects_pydantic_fields():
    """新增字段应自动出现在两种导出格式中（无需手写 schema）。"""

    class ExtendedArgs(BaseModel):
        value: str
        extra_flag: bool = False

    async def handler(args: ExtendedArgs):
        return None

    reg = ToolRegistry()
    reg.register(Tool(name="ext", description="d", args_schema=ExtendedArgs, handler=handler))

    openai_props = reg.to_openai_schema()[0]["function"]["parameters"]["properties"]
    anthropic_props = reg.to_anthropic_schema()[0]["input_schema"]["properties"]
    assert "extra_flag" in openai_props
    assert "extra_flag" in anthropic_props


def test_build_default_registry_has_all_tools():
    reg = build_default_registry()
    expected = {
        "search_knowledge",
        "find_technician",
        "check_availability",
        "create_appointment",
        "get_user_preferences",
    }
    assert set(reg.names()) == expected
    # 两种格式都能为全部工具导出
    assert len(reg.to_openai_schema()) == len(expected)
    assert len(reg.to_anthropic_schema()) == len(expected)
