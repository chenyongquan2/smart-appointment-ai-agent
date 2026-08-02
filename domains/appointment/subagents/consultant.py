"""consultant 子 Agent —— 负责服务咨询（Phase 7）。

只持有知识库检索工具：回答价格、项目、营业时间、注意事项等信息类问题。不具备写库的
预约能力（不含 create_appointment）。
"""

from __future__ import annotations

from harness.subagents.base import SubAgent

# 模块级常量：咨询顾问子 Agent（frozen 纯数据）。
CONSULTANT_SUBAGENT = SubAgent(
    name="consultant",
    # description 帮主 Agent 区分「咨询信息」与「下单预约」——前者派 consultant，后者派 appointment。
    description=(
        "门店咨询顾问：回答关于服务项目、价格、营业时间、技师介绍、注意事项等"
        "信息类问题。当用户在咨询信息而非直接下单预约时派给它。"
    ),
    # 刻意只给一个「只读」的知识库检索工具——拿不到 create_appointment，
    # 故本子 Agent 在能力上就「不可能误下单」（最小权限原则的直接体现）。
    tool_names=("search_knowledge",),
    system_prompt=(
        "你是按摩/推拿门店的咨询顾问，负责解答顾客关于服务、价格、营业信息等问题。\n"
        "\n"
        "工作方式（TAO 循环）：\n"
        "- 用知识库检索工具找到与问题最相关的资料，再据此作答。\n"
        "- 检索结果不足以回答时，如实说明，不要编造价格或政策。\n"
        "- 你不负责创建预约；若用户想直接下单，提示其转由预约流程办理。\n"
        "- 用简洁友好的简体中文回复。"
    ),
)
