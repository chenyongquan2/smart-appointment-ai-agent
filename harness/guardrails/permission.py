"""危险操作权限闸门（Phase 5）。

危险（``dangerous``）工具在分发前 MUST 先经一个**可注入**的权限策略判定：策略接收
（工具、入参）返回一个结构化 :class:`Decision`（放行 / 拒绝 + 理由）。被拒时不执行
handler，由 ``ToolRegistry`` 把结构化拒绝结果交回 ``AgentLoop`` 经错误回灌路径喂给模型。

策略以一个可调用对象表达：``Callable[[Tool, dict], Decision]``。未注入策略时默认放行
（:func:`allow_all`），保持既有行为不破坏现有测试与 evals（见 design.md D5）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:  # 仅类型注解用，避免运行时反向依赖
    from harness.tools.base import Tool

__all__ = ["Decision", "PermissionPolicy", "allow_all"]


@dataclass(frozen=True)
class Decision:
    """权限判定结果：是否放行 + 拒绝理由。"""

    allow: bool
    reason: str = ""

    @classmethod
    def allowed(cls) -> "Decision":
        return cls(allow=True)

    @classmethod
    def denied(cls, reason: str) -> "Decision":
        return cls(allow=False, reason=reason)


# 权限策略类型：给定（工具, 入参）返回放行/拒绝决定。
PermissionPolicy = Callable[["Tool", dict[str, Any]], Decision]


def allow_all(tool: "Tool", args: dict[str, Any]) -> Decision:
    """默认策略：放行一切（保持未配置策略时的既有行为）。"""
    return Decision.allowed()
