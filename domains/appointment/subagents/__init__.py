"""预约域的子 Agent 集。

三个专员各持工具子集：预约（可写库）/ 咨询（只读检索）/ 行为分析（只读偏好）。
子 Agent 的**机制**（SubAgent 结构、注册中心、delegate 派生）是域无关的，留在
`harness/subagents/`；这里只声明「本域有哪几个专员、各管什么、各持哪些工具」。
"""

from domains.appointment.subagents.appointment import APPOINTMENT_SUBAGENT
from domains.appointment.subagents.consultant import CONSULTANT_SUBAGENT
from domains.appointment.subagents.user_behavior import USER_BEHAVIOR_SUBAGENT

# 顺序与领域包化之前 build_default_subagent_registry 的注册顺序一致。
SUBAGENTS = (APPOINTMENT_SUBAGENT, CONSULTANT_SUBAGENT, USER_BEHAVIOR_SUBAGENT)

__all__ = [
    "SUBAGENTS",
    "APPOINTMENT_SUBAGENT",
    "CONSULTANT_SUBAGENT",
    "USER_BEHAVIOR_SUBAGENT",
]
