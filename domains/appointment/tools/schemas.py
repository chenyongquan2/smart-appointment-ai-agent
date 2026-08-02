"""工具入参的 Pydantic v2 schema（单一真相源）。

时间/时长字段沿用 Phase 1 ``AppointmentSlots`` 的约定（``YYYY-MM-DD HH:MM`` 字符串、
分钟数时长）。这些 schema 既用于分发前的入参校验，也用于导出 Anthropic/OpenAI tools schema。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# 说明：每个 Field 的 description 不只是注释——它会被 model_json_schema() 抽出来，
# 经 registry 导出进 tools schema 给 LLM 看。所以这里的措辞「就是写给模型的提示词」，
# 直接影响模型怎么填参数；ge/le/default 这些约束则在 Tool.run 校验时强制生效。


class SearchKnowledgeArgs(BaseModel):
    """search_knowledge 入参。"""

    query: str = Field(description="用户的咨询/检索问题文本。")  # 必填：无 default 即必须提供
    # ge=1, le=20：闭区间约束 [1,20]，越界会在校验时被 Pydantic 拒掉；default=3 即模型不传时取 3。
    top_k: int = Field(default=3, ge=1, le=20, description="返回的相关文档数量，默认 3。")
    # str | None + default=None：可选字段，留空表示「不按分类过滤」（注意是 None，不是空串）。
    category: str | None = Field(
        default=None, description="可选的分类过滤（如 服务项目/营业时间）；不限定则留空。"
    )


class FindTechnicianArgs(BaseModel):
    """find_technician 入参。字段语义沿用 AppointmentSlots。"""

    # 易误解点：start_time 是「字符串」而非 datetime——沿用 Phase 1 AppointmentSlots 的
    # 文本约定（"2026-06-19 14:30"），校验只保证它是 str，不校验日期是否合法/可解析。
    start_time: str = Field(
        description="预约起始时间，标准格式 YYYY-MM-DD HH:MM。"
    )
    # 同样是字符串，且带中文单位「分钟」（如 "180分钟"），不是纯数字——下游 service 自行解析。
    duration: str = Field(description="服务时长，分钟数格式，如 180分钟。")
    # 下面四个均为可选：default 用「中文占位串」（未知/无）而非 None——下游按这些哨兵值判断「未指定」。
    project: str = Field(default="未知", description="服务项目（如 按摩/推拿）。")
    preference: str = Field(default="无", description="用户倾向（如 力气大/力气小/无）。")
    gender: str = Field(default="未知", description="技师性别倾向（男/女/未知）。")
    technician_name: str = Field(
        default="未知", description="指定技师姓名；未指定则为 未知。"
    )


class CheckAvailabilityArgs(BaseModel):
    """check_availability 入参。"""

    # technician_id 是 int（数值 ID），与上面 find_technician 用「姓名」定位技师互补：
    # 一般先 find_technician 拿到 id，再用这个 id 查某段时间是否可约。
    technician_id: int = Field(description="技师 ID。")
    start_time: str = Field(description="起始时间，标准格式 YYYY-MM-DD HH:MM。")
    duration: str = Field(description="服务时长，分钟数格式，如 60分钟。")


class CreateAppointmentArgs(BaseModel):
    """create_appointment 入参。"""

    # 这是唯一「写库」的工具（其 Tool 标了 dangerous=True），分发前会过权限闸门。
    technician_id: int = Field(description="要预约的技师 ID。")
    start_time: str = Field(description="起始时间，标准格式 YYYY-MM-DD HH:MM。")
    duration: str = Field(description="服务时长，分钟数格式，如 60分钟。")
    # 比查询类工具多一个必填 session_id：下单需绑定到具体会话，用于隔离与落库记录。
    session_id: str = Field(description="会话 ID，用于隔离与记录。")
    project: str = Field(default="未知", description="服务项目（如 按摩/推拿）。")


class GetUserPreferencesArgs(BaseModel):
    """get_user_preferences 入参。"""

    user_id: str = Field(description="用户 ID。")
    # bool 开关，default=False：仅当模型显式置 True 才额外跑较重的行为模式分析（省算力）。
    include_patterns: bool = Field(
        default=False, description="是否一并返回行为模式分析（analyze_user_patterns）。"
    )
