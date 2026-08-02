"""ToolRegistry：统一注册工具、按名分发、导出 LLM tools schema。

- 注册：重名报错。
- 分发：先用工具 args_schema 校验原始参数，再执行 handler；未知名报错。
- 导出：基于各工具 Pydantic args_schema 的 model_json_schema()，生成 OpenAI 与
  Anthropic 两种格式（单一真相源 = Pydantic 模型）。
"""

from __future__ import annotations

from typing import Any, Optional

from harness.guardrails.permission import Decision, PermissionPolicy, allow_all
from harness.tools.base import Tool


class ToolRegistry:
    """工具注册中心。

    Args:
        permission: 可选权限策略；对 ``dangerous`` 工具在执行 handler 前先判定，
            拒绝时不执行、返回结构化拒绝结果。``None`` 时默认放行（保持既有行为）。
    """

    def __init__(self, permission: Optional[PermissionPolicy] = None) -> None:
        # 工具表：以「工具名」为键。用 dict 而非 list，是为了 O(1) 按名分发；
        # 也天然保证「一名一工具」（重名会在 register 里被拦下）。
        self._tools: dict[str, Tool] = {}
        # 权限策略：一个「给(tool, args)、返回放行/拒绝」的可调用对象。
        # 缺省 allow_all = 全部放行，行为与无权限闸门时完全一致（向后兼容）。
        self._permission: PermissionPolicy = permission or allow_all

    def register(self, tool: Tool) -> None:
        """注册工具；name 已存在则报错，拒绝覆盖。"""
        # 重名即报错（而非静默覆盖）：避免「后注册的工具悄悄顶掉同名工具」这类隐蔽 bug。
        if tool.name in self._tools:
            raise ValueError(f"工具 '{tool.name}' 已注册，拒绝覆盖。")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        """按名取工具；不存在则报错。"""
        # 取不到就抛 KeyError（不返回 None）：让「调用了不存在的工具」尽早暴露成明确错误。
        if name not in self._tools:
            raise KeyError(f"未注册的工具：'{name}'。")
        return self._tools[name]

    def names(self) -> list[str]:
        # 当前已注册的全部工具名（dict 迭代即键）；供 system prompt 列举工具、subset 校验等用。
        return list(self._tools)

    def subset(self, names: list[str]) -> "ToolRegistry":
        """构建仅含指定工具的子集 registry（切片），供子 Agent 使用（Phase 7）。

        复用既有 ``Tool`` 实例（不复制、不重写业务逻辑），并沿用本 registry 的权限
        策略。含未注册的工具名时报错（与 ``get`` 一致）。子集 registry 的注册/分发/
        导出 schema 行为与全量 registry 完全一致。
        """
        # 新建一个空 registry，沿用「同一个」权限策略（子 Agent 不该比父更宽松）。
        sub = ToolRegistry(permission=self._permission)
        for name in names:
            # self.get(name) 复用「同一个 Tool 实例」放进子集——不拷贝、不重写业务逻辑。
            # 名字不存在会在 get 里抛 KeyError，子集构建即失败（不会悄悄少一个工具）。
            sub.register(self.get(name))
        return sub

    async def dispatch(self, name: str, raw_args: dict[str, Any]) -> Any:
        """按名分发：危险工具先过权限闸门，再校验入参（Pydantic）后执行 handler。

        危险工具被策略拒绝时 MUST NOT 执行 handler，返回结构化拒绝结果
        （``{"success": False, "denied": True, "reason": ...}``），由 ``AgentLoop``
        经错误回灌路径喂回模型。只读工具与默认放行策略下行为与既有一致。
        """
        # ① 按名取工具（未注册即在此抛 KeyError）。
        tool = self.get(name)
        # ② 权限闸门：只拦「危险工具」，只读工具直接跳过这段（少一次策略调用）。
        if tool.dangerous:
            # 策略返回 Decision(allow, reason)；reason 在拒绝时解释「为何不让做」。
            decision: Decision = self._permission(tool, raw_args)
            if not decision.allow:
                # 关键：被拒时「绝不执行 handler」，而是回一个结构化拒绝结果。
                # 不抛异常——让 AgentLoop 把它当普通工具结果喂回模型，模型可据 reason 改口/换法。
                return {
                    "success": False,
                    "denied": True,
                    "reason": decision.reason,
                }
        # ③ 放行后才真正执行：tool.run 内部先做 Pydantic 入参校验，再调 handler（见 base.py）。
        return await tool.run(raw_args)

    # ↓↓ to_openai_schema / to_anthropic_schema 是「单一真相源」的体现：两者都从工具的
    #    Pydantic args_schema 现场生成，故 schema 永远与校验规则一致，绝不会两处脱节。
    def to_openai_schema(self) -> list[dict[str, Any]]:
        """导出 OpenAI function-calling 格式。"""
        # 形如 [{"type":"function","function":{"name","description","parameters"}}, ...]，
        # 由 AgentLoop 在 bind_tools 时喂给 LLM，让模型「知道有哪些工具、各收什么参数」。
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    # model_json_schema()：把 Pydantic 模型转成 JSON Schema（字段/类型/默认/约束），
                    # 即「参数表」。这一步保证「校验用的 schema」与「告诉模型的 schema」是同一份。
                    "parameters": tool.args_schema.model_json_schema(),
                },
            }
            for tool in self._tools.values()
        ]

    def to_anthropic_schema(self) -> list[dict[str, Any]]:
        """导出 Anthropic tools 格式。"""
        # 与 OpenAI 版同源、仅外层结构不同：Anthropic 用平铺的 name/description/input_schema。
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.args_schema.model_json_schema(),
            }
            for tool in self._tools.values()
        ]
