"""ToolRegistry：统一注册工具、按名分发、导出 LLM tools schema。

- 注册：重名报错。
- 分发：先用工具 args_schema 校验原始参数，再执行 handler；未知名报错。
- 导出：基于各工具 Pydantic args_schema 的 model_json_schema()，生成 OpenAI 与
  Anthropic 两种格式（单一真相源 = Pydantic 模型）。
"""

from __future__ import annotations

from typing import Any

from harness.tools.base import Tool


class ToolRegistry:
    """工具注册中心。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册工具；name 已存在则报错，拒绝覆盖。"""
        if tool.name in self._tools:
            raise ValueError(f"工具 '{tool.name}' 已注册，拒绝覆盖。")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        """按名取工具；不存在则报错。"""
        if name not in self._tools:
            raise KeyError(f"未注册的工具：'{name}'。")
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools)

    async def dispatch(self, name: str, raw_args: dict[str, Any]) -> Any:
        """按名分发：校验入参（Pydantic）后执行 handler。"""
        tool = self.get(name)
        return await tool.run(raw_args)

    def to_openai_schema(self) -> list[dict[str, Any]]:
        """导出 OpenAI function-calling 格式。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.args_schema.model_json_schema(),
                },
            }
            for tool in self._tools.values()
        ]

    def to_anthropic_schema(self) -> list[dict[str, Any]]:
        """导出 Anthropic tools 格式。"""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.args_schema.model_json_schema(),
            }
            for tool in self._tools.values()
        ]


def build_default_registry() -> ToolRegistry:
    """注册全部内置工具，返回可用的 registry。"""
    from harness.tools.appointment import create_appointment
    from harness.tools.availability import check_availability
    from harness.tools.knowledge import search_knowledge
    from harness.tools.preference import get_user_preferences
    from harness.tools.technician import find_technician

    registry = ToolRegistry()
    for tool in (
        search_knowledge,
        find_technician,
        check_availability,
        create_appointment,
        get_user_preferences,
    ):
        registry.register(tool)
    return registry
