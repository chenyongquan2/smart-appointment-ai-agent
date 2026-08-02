"""get_user_preferences 工具：薄封装 UserBehaviorService。

只读查询工具：读某用户的长期偏好（偏好技师、惯常时段等），可选附带行为模式分析，
用于个性化推荐/预约。薄封装：直接转交 service 的两个方法，本工具不算任何偏好。
"""

from __future__ import annotations

from typing import Any

from harness.tools.base import Tool
from domains.appointment.tools.schemas import GetUserPreferencesArgs


async def _handler(args: GetUserPreferencesArgs) -> dict[str, Any]:
    # 延迟 import：仅在调用本工具时才加载 UserBehaviorService（避免导入即拉起其依赖）。
    from services.user_behavior_service import UserBehaviorService

    service = UserBehaviorService()
    # ① 必返回的基础结果：回显 user_id + service 查到的偏好（偏好内容形状由 service 决定，
    #    工具层原样透传，不重组、不挑字段）。
    result: dict[str, Any] = {
        "user_id": args.user_id,
        "preferences": service.get_user_preferences(args.user_id),
    }
    # ② 可选增量：仅当调用方显式要 include_patterns 时，才多调一次较重的模式分析。
    #    设计意图——按需付费，不要每次都跑 analyze（它通常比单纯读偏好更耗）。
    if args.include_patterns:
        result["patterns"] = service.analyze_user_patterns(args.user_id)
    return result


# 声明工具四要素；未设 dangerous → 默认 False（只读，分发时直接放行）。
get_user_preferences = Tool(
    name="get_user_preferences",
    description=(
        "读取某个用户的长期偏好（如偏好技师、时间段）。可选地一并返回行为模式分析。"
        "用于在预约/推荐时个性化决策。"
    ),
    args_schema=GetUserPreferencesArgs,
    handler=_handler,
)
