"""工具抽象基类。

每个工具是 ``services/`` 的薄封装，声明四要素：
``name`` / ``description`` / ``args_schema`` / ``handler``。
handler 统一为 async（因 ``KnowledgeService.search`` 是 async，且对齐 Phase 3 的
async agent loop），签名为 ``async def handler(args: BaseModel) -> Any``。

工具 MUST NOT 重写业务逻辑——仅把已校验的参数转交给对应 service 方法。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel


@dataclass(frozen=True)
class Tool:
    """一个可被 LLM 调用的工具。

    Attributes:
        name: 唯一工具名（snake_case），用于注册与分发。
        description: 面向模型的说明书——决定模型何时调用本工具。
        args_schema: 入参的 Pydantic v2 模型；分发前用它校验原始参数。
        handler: ``async def handler(args: args_schema) -> Any``，
            接收已校验的 args 模型实例，内部调用 services/。
        dangerous: 是否为有副作用的危险操作（如写库的 ``create_appointment``）。
            危险工具在分发前须经权限闸门判定（见 ``harness/guardrails/permission``）；
            只读查询工具保持默认 ``False``。
    """

    name: str
    description: str
    args_schema: type[BaseModel]
    handler: Callable[[BaseModel], Awaitable[Any]]
    dangerous: bool = False

    async def run(self, raw_args: dict[str, Any]) -> Any:
        """校验原始参数并执行 handler。"""
        validated = self.args_schema(**raw_args)
        return await self.handler(validated)
