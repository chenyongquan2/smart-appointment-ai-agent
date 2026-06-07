"""get_user_preferences 工具：薄封装 UserBehaviorService。"""

from __future__ import annotations

from typing import Any

from harness.tools.base import Tool
from harness.tools.schemas import GetUserPreferencesArgs


async def _handler(args: GetUserPreferencesArgs) -> dict[str, Any]:
    from services.user_behavior_service import UserBehaviorService

    service = UserBehaviorService()
    result: dict[str, Any] = {
        "user_id": args.user_id,
        "preferences": service.get_user_preferences(args.user_id),
    }
    if args.include_patterns:
        result["patterns"] = service.analyze_user_patterns(args.user_id)
    return result


get_user_preferences = Tool(
    name="get_user_preferences",
    description=(
        "读取某个用户的长期偏好（如偏好技师、时间段）。可选地一并返回行为模式分析。"
        "用于在预约/推荐时个性化决策。"
    ),
    args_schema=GetUserPreferencesArgs,
    handler=_handler,
)
