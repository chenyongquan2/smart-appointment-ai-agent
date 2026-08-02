"""find_technician 工具：薄封装既有技师查找逻辑。

复用 ``services/technician_matching.py`` 的 TechnicianFinder（指定技师优先，
否则按 gender/preference 过滤 + 查可用），不在工具层重写匹配规则。

历史：本工具曾横向依赖 ``agents/``（违反"单向向下"），是 Phase 2 为避免重写业务逻辑
而留的已知取舍。change ``domain-packages`` 把 TechnicianFinder 下沉到 ``services/``，
这笔债已还清——现在是标准的 harness → services 单向依赖。
"""

from __future__ import annotations

from typing import Any

from harness.tools.base import Tool
from domains.appointment.tools.schemas import FindTechnicianArgs


async def _handler(args: FindTechnicianArgs) -> dict[str, Any] | None:
    # 延迟 import：仅在调用本工具时才加载 TechnicianFinder（避免导入即拉起其依赖）。
    from services.technician_matching import TechnicianFinder

    finder = TechnicianFinder()
    # 把 6 个独立入参打包成 finder 期望的 appointment_history 字典——纯换形状、不挑不算。
    # 各字段典型取值：start_time "2026-06-19 14:00"、duration "180分钟"、project "按摩"、
    # preference "力气大"/"无"、gender "男"/"女"/"未知"、technician_name 指定姓名或 "未知"。
    appointment_history = {
        "start_time": args.start_time,
        "duration": args.duration,
        "project": args.project,
        "preference": args.preference,
        "gender": args.gender,
        "technician_name": args.technician_name,
    }
    # 匹配规则（指定优先 / 否则按性别+偏好过滤 + 查可用 / 不可用则推荐相似技师）整套都在
    # finder 里，工具层一行转交、绝不重写。返回技师信息字典；找不到时为 None。
    # yield_func 为 None：finder 本可流式吐 thought，但工具层不产出 thought 流，
    # 可观测交给上层（Phase 3 loop 的 tracer）统一负责，故这里显式关掉。
    #
    # 必须 await：finder 内部要做向量化（远程 HTTP）。这里曾经是同步调用，导致本
    # async handler 在等待期间冻住整个事件循环——见 change fix-technician-embedding-blocking。
    return await finder.find_technician_with_thought(appointment_history, yield_func=None)


# 声明工具四要素；未设 dangerous → 默认 False（只读查找，分发时直接放行）。
find_technician = Tool(
    name="find_technician",
    description=(
        "根据预约时间、时长、项目、性别与力度偏好查找一位可用技师。若用户指定了技师姓名，"
        "优先查该技师是否有空；不可用时会按专长相似度推荐替代技师。返回技师信息字典，"
        "或在找不到时返回 null。"
    ),
    args_schema=FindTechnicianArgs,
    handler=_handler,
)
