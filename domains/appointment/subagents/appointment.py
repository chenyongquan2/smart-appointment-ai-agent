"""appointment 子 Agent —— 负责预约办理（Phase 7）。

持有预约领域的工具子集：查技师、查可用性、创建预约、读用户偏好。在独立上下文里
自主完成「查技师 → 不可用则改查 → 创建预约」这类多步组合。
"""

from __future__ import annotations

from harness.subagents.base import SubAgent

# 模块级常量：一个 frozen SubAgent 实例（纯数据，无行为）。
# 由 build_default_subagent_registry() 在启动时注册进 SubAgentRegistry。
APPOINTMENT_SUBAGENT = SubAgent(
    name="appointment",  # 唯一名；主 Agent 调 delegate 时用它指定派给谁
    # description 面向「主 Agent 的 LLM」：它据此判断「何时该把任务派给 appointment」。
    description=(
        "预约办理专员：处理与「约技师 / 排时间 / 创建或确认预约」相关的任务。"
        "能查找符合时间、项目、性别、偏好的技师，核对其可用性，并在信息齐全、技师可用时"
        "创建预约。涉及具体下单/改约/查空档时派给它。"
    ),
    # 这是三个子 Agent 里唯一持有写库工具（create_appointment）的——它是真正能「下单」的角色。
    # SubAgent.run 会据此从全量 registry 切出子集，故本子 Agent 只能看到/调用这 4 个工具。
    tool_names=(
        "find_technician",       # 查技师
        "check_availability",    # 查某技师在目标时段是否可用
        "create_appointment",    # 写库下单（仅本子 Agent 拥有）
        "get_user_preferences",  # 读用户偏好辅助选技师/时段
    ),
    system_prompt=(
        "你是按摩/推拿门店的预约办理专员，专注于把顾客的预约需求落实成一次具体预约。\n"
        "\n"
        "工作方式（TAO 循环）：\n"
        "- 用工具查找合适技师、核对其在目标时间段是否可用；必要时参考用户偏好。\n"
        "- 若首选技师不可用，自主改查替代技师，不要直接放弃。\n"
        "- 仅在技师已确认可用、且时间/项目等信息齐全时才创建预约。\n"
        "- 信息不足时，明确向用户说明还缺哪些信息，不要臆测下单。\n"
        "- 完成或无法完成时，用简洁友好的简体中文给出明确结论。"
    ),
)
