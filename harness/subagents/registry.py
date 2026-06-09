"""SubAgentRegistry —— 子 Agent 注册中心（Phase 7）。

注册、按名查找、列出可派生的子 Agent。重名注册报错（与 ``ToolRegistry`` 一致）。
``delegate`` 工具与主 system prompt 都从这里读取「团队成员」清单。
"""

from __future__ import annotations

from harness.subagents.base import SubAgent


class SubAgentRegistry:
    """子 Agent 注册中心。"""

    def __init__(self) -> None:
        self._agents: dict[str, SubAgent] = {}

    def register(self, agent: SubAgent) -> None:
        """注册子 Agent；name 已存在则报错，拒绝覆盖。"""
        if agent.name in self._agents:
            raise ValueError(f"子 Agent '{agent.name}' 已注册，拒绝覆盖。")
        self._agents[agent.name] = agent

    def get(self, name: str) -> SubAgent:
        """按名取子 Agent；不存在则报错。"""
        if name not in self._agents:
            raise KeyError(f"未注册的子 Agent：'{name}'。")
        return self._agents[name]

    def has(self, name: str) -> bool:
        return name in self._agents

    def names(self) -> list[str]:
        return list(self._agents)

    def all(self) -> list[SubAgent]:
        return list(self._agents.values())


def build_default_subagent_registry() -> SubAgentRegistry:
    """注册全部内置子 Agent（预约 / 咨询 / 行为分析），返回可用的注册中心。"""
    from harness.subagents.appointment import APPOINTMENT_SUBAGENT
    from harness.subagents.consultant import CONSULTANT_SUBAGENT
    from harness.subagents.user_behavior import USER_BEHAVIOR_SUBAGENT

    registry = SubAgentRegistry()
    for agent in (APPOINTMENT_SUBAGENT, CONSULTANT_SUBAGENT, USER_BEHAVIOR_SUBAGENT):
        registry.register(agent)
    return registry
