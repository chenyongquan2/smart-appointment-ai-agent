"""预约槽位抽取的结构化输出 schema。

用 Pydantic v2 + function calling 约束模型输出,取代裸 JSON + json.loads
(见 OpenSpec change: phase-1-structured-output)。字段与既有 InputParser 输出一一对应,
保证调用方 ``data.get(...)`` 用法向后兼容。
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class AppointmentSlots(BaseModel):
    """从用户输入中抽取的预约槽位。字段语义沿用既有 InputParser 约定。"""

    gender: str = Field(
        default="未知", description="技师性别(如 男/女/未知)。"
    )
    start_time: str = Field(
        default="未知",
        description=(
            "预约起始时间,必须转换为标准格式 YYYY-MM-DD HH:MM。"
            "如用户说今天下午3点,转换为当前日期 15:00;说明天上午10点,转换为明天日期 10:00。"
            "只说时间没说日期则默认今天。完全没有时间信息则为 未知。"
        ),
    )
    duration: str = Field(
        default="未知",
        description="服务时长,统一转换为分钟数格式,如 180分钟、60分钟。没有明确时长则为 未知。",
    )
    project: str = Field(
        default="未知", description="服务项目(如 按摩/推拿/未知)。"
    )
    preference: str = Field(
        default="未知", description="用户倾向(如 力气大/力气小/无)。"
    )
    technician_name: str = Field(
        default="未知",
        description="指定技师姓名(如用户明确提到张伟、李小美等),否则为 未知。",
    )
    confirmation: str = Field(
        default="未知",
        description=(
            "如用户在回应技师推荐的确认问题,提取其回复内容(如 是/好/可以/不/不要 等),"
            "否则为 未知。"
        ),
    )
    info_complete: bool = Field(
        default=False,
        description=(
            "必需信息是否齐全:1) 若指定了技师名(technician_name 不为未知),"
            "需 start_time、project、duration 都不为未知;"
            "2) 若未指定技师名,需 start_time、project、duration、gender 都不为未知。"
        ),
    )
    unrelated: bool = Field(
        default=False,
        description=(
            "用户问题是否与预约无关(如问天气、闲聊)。注意:对推荐技师的确认回复"
            "(是/好/不/不要等)不应标记为无关,应为 false。"
        ),
    )
    missing_info: List[str] = Field(
        default_factory=list,
        description="若 info_complete 为 false,列出缺少的关键信息,如 [start_time, project]。",
    )
