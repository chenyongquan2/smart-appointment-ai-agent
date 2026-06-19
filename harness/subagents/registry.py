"""SubAgentRegistry —— 子 Agent 注册中心（Phase 7）。

注册、按名查找、列出可派生的子 Agent。重名注册报错（与 ``ToolRegistry`` 一致）。
``delegate`` 工具与主 system prompt 都从这里读取「团队成员」清单。
"""

from __future__ import annotations

from harness.subagents.base import SubAgent


class SubAgentRegistry:
    """子 Agent 注册中心。"""

    def __init__(self) -> None:
        # name → SubAgent 的字典；name 即唯一键，故下面查找/列举都是 O(1) 字典操作。
        self._agents: dict[str, SubAgent] = {}

    def register(self, agent: SubAgent) -> None:
        """注册子 Agent；name 已存在则报错，拒绝覆盖。"""
        # 重名即报错（fail-fast），而非静默覆盖：覆盖会让「到底跑哪个子 Agent」变得不可预测，
        # 是极难排查的 bug。宁可启动时就炸，逼调用方改名。与 ToolRegistry 的去重策略一致。
        if agent.name in self._agents:
            raise ValueError(f"子 Agent '{agent.name}' 已注册，拒绝覆盖。")
        self._agents[agent.name] = agent

    def get(self, name: str) -> SubAgent:
        """按名取子 Agent；不存在则报错。"""
        # 找不到就抛 KeyError，而非返回 None：调用方（如 delegate handler）才能尽早发现问题。
        # 注意 delegate 会先用 has() 探一下再 get()，避免把异常暴露给模型。
        if name not in self._agents:
            raise KeyError(f"未注册的子 Agent：'{name}'。")
        return self._agents[name]

    def has(self, name: str) -> bool:
        return name in self._agents  # delegate handler 用它先探后取，避免触发 get 的 KeyError

    def names(self) -> list[str]:
        return list(self._agents)  # dict 迭代即迭代 key，故得到全部子 Agent 名

    def all(self) -> list[SubAgent]:
        # 返回全部子 Agent 实例；delegate 的 description 与主 system prompt 据此渲染「团队成员」清单。
        return list(self._agents.values())


def build_default_subagent_registry() -> SubAgentRegistry:
    """注册全部内置子 Agent（预约 / 咨询 / 行为分析），返回可用的注册中心。"""
    # 在函数内部 import（而非模块顶部）：打破「registry ←→ 各子 Agent 模块」的潜在循环依赖，
    # 也让「注册哪些子 Agent」这件事集中在这一处、一目了然。
    from harness.subagents.appointment import APPOINTMENT_SUBAGENT
    from harness.subagents.consultant import CONSULTANT_SUBAGENT
    from harness.subagents.user_behavior import USER_BEHAVIOR_SUBAGENT

    registry = SubAgentRegistry()
    # 逐个注册三个内置子 Agent；任一重名都会在这里 fail-fast（见 register）。
    for agent in (APPOINTMENT_SUBAGENT, CONSULTANT_SUBAGENT, USER_BEHAVIOR_SUBAGENT):
        registry.register(agent)
    return registry
