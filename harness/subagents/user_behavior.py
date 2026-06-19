"""user_behavior 子 Agent —— 负责用户行为/偏好分析（Phase 7）。

只持有读取用户偏好的工具：解读顾客历史偏好（常约项目、偏好技师/性别/时段等），
为个性化推荐或回访提供依据。只读，不写库。
"""

from __future__ import annotations

from harness.subagents.base import SubAgent

# 模块级常量：用户行为分析子 Agent（frozen 纯数据）。
USER_BEHAVIOR_SUBAGENT = SubAgent(
    name="user_behavior",
    # description 界定它的专长是「分析这位用户的偏好」，与 consultant（通用知识）划清边界。
    description=(
        "用户行为分析专员：读取并解读某位用户的历史偏好（常约项目、偏好技师/性别/时段等），"
        "用于个性化建议或回访。当任务是「分析这位用户喜欢什么 / 给出个性化推荐依据」时派给它。"
    ),
    # 同样只给一个只读工具：本子 Agent 只「读+解读」用户偏好，既不写库也不检索通用知识。
    # 注意 get_user_preferences 与 appointment 子 Agent 共享——同一工具可被多个子 Agent 各取所需。
    tool_names=("get_user_preferences",),
    system_prompt=(
        "你是门店的用户行为分析专员，负责读取并解读顾客的历史偏好。\n"
        "\n"
        "工作方式（TAO 循环）：\n"
        "- 用偏好查询工具获取该用户的历史偏好数据，再据此给出结构化、可执行的解读。\n"
        "- 没有足够数据时如实说明，不要臆测。\n"
        "- 你不负责创建预约或检索通用知识，只聚焦该用户的偏好分析。\n"
        "- 用简洁的简体中文输出分析结论。"
    ),
)
