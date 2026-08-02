"""check_availability 工具：薄封装 AppointmentService.is_technician_available。

只读查询工具：判断某技师在某时间窗是否有空，不写任何数据（与 create_appointment 对照）。
典型用途——LLM 在真正下单前先调它确认档期。薄封装：算时间窗 + 转交 service，不写判空规则。
"""

from __future__ import annotations

from harness.tools.base import Tool
from domains.appointment.tools.schemas import CheckAvailabilityArgs
from domains.appointment.tools.time_utils import resolve_time_window


async def _handler(args: CheckAvailabilityArgs) -> dict[str, object]:
    # 延迟 import：只有真调用本工具时才加载会连库的 AppointmentService。
    from services.appointment_service import AppointmentService

    # ① 起始时间字符串 + 时长字符串 → (start, end) 时间窗；非法即就地返回错误。
    #    这是「输入兜底」而非业务逻辑：让模型拿到人话提示后下一轮补正参数。
    window = resolve_time_window(args.start_time, args.duration)
    if window is None:
        return {"available": False, "error": "时间或时长格式非法，无法判断可用性。"}

    start, end = window  # 两个 datetime，service 要的是 datetime 不是字符串
    service = AppointmentService()
    # ② 是否空闲的判断完全委托 service——本工具不知道、也不该知道冲突规则。
    #    易误解点：这里 technician_id 直接传 int（与写操作里要 str() 不同，因 service
    #    两个方法签名口径不一致）；薄封装只负责「贴合 service 的签名」，不统一口径。
    available = service.is_technician_available(args.technician_id, start, end)
    # ③ 回给 LLM 的极简结果：bool(...) 把 service 的真/假值规整成严格 True/False。
    return {"available": bool(available), "technician_id": args.technician_id}


# 声明工具四要素；未设 dangerous → 默认 False（只读，分发时直接放行，无需过权限闸门）。
check_availability = Tool(
    name="check_availability",
    description=(
        "检查指定技师在某个时间窗（起始时间 + 时长）是否空闲。返回 {available: bool}。"
        "在创建预约前用于确认档期。"
    ),
    args_schema=CheckAvailabilityArgs,
    handler=_handler,
)
