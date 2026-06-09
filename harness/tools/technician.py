"""find_technician 工具：薄封装既有技师查找逻辑。

复用 ``agents/appointment/technician_finder.py`` 的 TechnicianFinder（指定技师优先，
否则按 gender/preference 过滤 + 查可用），不在工具层重写匹配规则。

注意：本工具临时横向依赖 ``agents/``，违反严格的"单向向下"。这是 Phase 2 的已知取舍
（避免重写业务逻辑），Phase 3 迁移技师查找逻辑下沉后即可去除。
"""

from __future__ import annotations

from typing import Any

from harness.tools.base import Tool
from harness.tools.schemas import FindTechnicianArgs


async def _handler(args: FindTechnicianArgs) -> dict[str, Any] | None:
    from agents.appointment.technician_finder import TechnicianFinder

    finder = TechnicianFinder()
    appointment_history = {
        "start_time": args.start_time,
        "duration": args.duration,
        "project": args.project,
        "preference": args.preference,
        "gender": args.gender,
        "technician_name": args.technician_name,
    }
    # yield_func 为 None：工具层不产出 thought 流，由上层（Phase 3 loop）负责可观测。
    return finder.find_technician_with_thought(appointment_history, yield_func=None)


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
