"""任务分类的结构化输出 schema。

用 Pydantic v2 + function calling 约束模型输出,取代字符串解析
(见 OpenSpec change: phase-1-structured-output)。
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


TaskCategoryLiteral = Literal["appointment", "query", "pay", "statistics", "other"]


class TaskCategory(BaseModel):
    """用户/工作人员消息的意图分类结果。"""

    category: TaskCategoryLiteral = Field(
        description=(
            "本次任务的意图类别,只能是以下之一:"
            "appointment(预约任务:用户请求预约,或工作人员告知需延长服务时间);"
            "query(查询任务:咨询服务价格、项目、有哪些工作人员及其特点等);"
            "pay(支付任务:appointment 机器人告知用户已选定某工作人员做某项目);"
            "statistics(统计任务:工作人员上报已完成当前任务);"
            "other(其它:与上述均无关)。"
        )
    )
    reason: Optional[str] = Field(
        default=None, description="简要说明分类依据(可选)。"
    )
