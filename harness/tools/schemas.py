"""工具入参的 Pydantic v2 schema（单一真相源）。

时间/时长字段沿用 Phase 1 ``AppointmentSlots`` 的约定（``YYYY-MM-DD HH:MM`` 字符串、
分钟数时长）。这些 schema 既用于分发前的入参校验，也用于导出 Anthropic/OpenAI tools schema。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchKnowledgeArgs(BaseModel):
    """search_knowledge 入参。"""

    query: str = Field(description="用户的咨询/检索问题文本。")
    top_k: int = Field(default=3, ge=1, le=20, description="返回的相关文档数量，默认 3。")
    category: str | None = Field(
        default=None, description="可选的分类过滤（如 服务项目/营业时间）；不限定则留空。"
    )


class FindTechnicianArgs(BaseModel):
    """find_technician 入参。字段语义沿用 AppointmentSlots。"""

    start_time: str = Field(
        description="预约起始时间，标准格式 YYYY-MM-DD HH:MM。"
    )
    duration: str = Field(description="服务时长，分钟数格式，如 180分钟。")
    project: str = Field(default="未知", description="服务项目（如 按摩/推拿）。")
    preference: str = Field(default="无", description="用户倾向（如 力气大/力气小/无）。")
    gender: str = Field(default="未知", description="技师性别倾向（男/女/未知）。")
    technician_name: str = Field(
        default="未知", description="指定技师姓名；未指定则为 未知。"
    )


class CheckAvailabilityArgs(BaseModel):
    """check_availability 入参。"""

    technician_id: int = Field(description="技师 ID。")
    start_time: str = Field(description="起始时间，标准格式 YYYY-MM-DD HH:MM。")
    duration: str = Field(description="服务时长，分钟数格式，如 60分钟。")


class CreateAppointmentArgs(BaseModel):
    """create_appointment 入参。"""

    technician_id: int = Field(description="要预约的技师 ID。")
    start_time: str = Field(description="起始时间，标准格式 YYYY-MM-DD HH:MM。")
    duration: str = Field(description="服务时长，分钟数格式，如 60分钟。")
    session_id: str = Field(description="会话 ID，用于隔离与记录。")
    project: str = Field(default="未知", description="服务项目（如 按摩/推拿）。")


class GetUserPreferencesArgs(BaseModel):
    """get_user_preferences 入参。"""

    user_id: str = Field(description="用户 ID。")
    include_patterns: bool = Field(
        default=False, description="是否一并返回行为模式分析（analyze_user_patterns）。"
    )
