"""create_appointment 工具：薄封装 AppointmentService.save_appointment。"""

from __future__ import annotations

from harness.tools.base import Tool
from harness.tools.schemas import CreateAppointmentArgs
from harness.tools.time_utils import resolve_time_window


async def _handler(args: CreateAppointmentArgs) -> dict[str, object]:
    from services.appointment_service import AppointmentService

    window = resolve_time_window(args.start_time, args.duration)
    if window is None:
        return {"success": False, "error": "时间或时长格式非法，无法创建预约。"}

    start, end = window
    appointment_history = {
        "start_time": args.start_time,
        "duration": args.duration,
        "project": args.project,
        "technician_id": args.technician_id,
    }
    service = AppointmentService()
    success = service.save_appointment(
        technician_id=str(args.technician_id),
        start_time=start,
        end_time=end,
        appointment_history=appointment_history,
        session_id=args.session_id,
    )
    return {
        "success": bool(success),
        "technician_id": args.technician_id,
        "start_time": args.start_time,
    }


create_appointment = Tool(
    name="create_appointment",
    description=(
        "为指定技师在某个时间窗创建预约并落库。仅在已确认技师可用、信息齐全时调用。"
        "返回 {success: bool}。"
    ),
    args_schema=CreateAppointmentArgs,
    handler=_handler,
    dangerous=True,  # 写库的副作用操作，分发前须经权限闸门（Phase 5）
)
