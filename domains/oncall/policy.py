"""OnCall 值守域的权限策略：只读红线。

**拒绝一切 `dangerous=True` 的工具。**

当前本域注册的两个工具都是只读（`dangerous=False`），所以这条策略**现在不会拒绝任何
东西**——那正是要点：它是**防线，不是开关**。将来谁往值守域加了写操作工具（改配置、
重启服务、提交代码），会在分发闸门被拦下，而不是等 code review 发现或指望 system
prompt 的自觉。

路线图的设计判断 6 写得很明确：「oncall 工具全部只读（代码绝不改、绝不提 PR），红线靠
`harness/guardrails/permission.py` 硬 enforce，不靠 prompt 自觉」。

change `domain-packages` 特意把 policy 接进了 `ToolRegistry`（此前从未接过线），
本域是它第一个**真正有约束力**的使用者。
"""

from __future__ import annotations

from typing import Any

from harness.guardrails.permission import Decision
from harness.tools.base import Tool

__all__ = ["POLICY", "read_only"]

_DENY_REASON = (
    "值守域只读：本域不执行任何写操作（改配置、重启服务、提交代码等）。"
    "该限制由权限策略硬性保证，请改用只读方式排查，或把变更交给有权限的同事执行。"
)


def read_only(tool: Tool, args: dict[str, Any]) -> Decision:
    """拒绝一切危险工具；只读工具放行。"""
    if tool.dangerous:
        return Decision.denied(_DENY_REASON)
    return Decision.allowed()


POLICY = read_only
