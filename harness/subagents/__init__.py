"""harness 子 Agent 层（Phase 7：子 Agent / delegate 派生）。

把领域能力（预约 / 咨询 / 行为分析）沉淀为专用子 Agent，由主 Agent 通过 ``delegate``
工具自主派生——而非硬编码路由。每个子 Agent 在独立上下文、独立工具子集里复用
``AgentLoop`` 跑一次 mini TAO 循环，结果汇总回主 Agent。
"""

from harness.subagents.base import SubAgent
from harness.subagents.delegate import build_delegate_tool
from harness.subagents.registry import (
    SubAgentRegistry,
    build_default_subagent_registry,
)

__all__ = [
    "SubAgent",
    "SubAgentRegistry",
    "build_default_subagent_registry",
    "build_delegate_tool",
]
