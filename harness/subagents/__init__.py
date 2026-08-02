"""harness 子 Agent 层的**域无关**部分（Phase 7：子 Agent / delegate 派生）。

``SubAgent`` 结构 + ``SubAgentRegistry`` + ``delegate`` 工具的构建。具体子 Agent
（预约 / 咨询 / 行为分析）**不在这里**——它们随领域包走（见 ``domains/``）。

机制不变：每个子 Agent 在独立上下文、独立工具子集里复用 ``AgentLoop`` 跑一次 mini
TAO 循环，由主 Agent 通过 ``delegate`` 自主派生，而非硬编码路由。
"""

from harness.subagents.base import SubAgent
from harness.subagents.delegate import build_delegate_tool
from harness.subagents.registry import SubAgentRegistry

__all__ = ["SubAgent", "SubAgentRegistry", "build_delegate_tool"]
