"""check_availability 工具：薄封装 AppointmentService.is_technician_available。"""

from __future__ import annotations

from harness.tools.base import Tool
from harness.tools.schemas import CheckAvailabilityArgs
from harness.tools.time_utils import resolve_time_window


async def _handler(args: CheckAvailabilityArgs) -> dict[str, object]:
    from services.appointment_service import AppointmentService

    window = resolve_time_window(args.start_time, args.duration)
    if window is None:
        return {"available": False, "error": "时间或时长格式非法，无法判断可用性。"}

    start, end = window
    service = AppointmentService()
    available = service.is_technician_available(args.technician_id, start, end)
    return {"available": bool(available), "technician_id": args.technician_id}


check_availability = Tool(
    name="check_availability",
    description=(
        "检查指定技师在某个时间窗（起始时间 + 时长）是否空闲。返回 {available: bool}。"
        "在创建预约前用于确认档期。"
    ),
    args_schema=CheckAvailabilityArgs,
    handler=_handler,
)
