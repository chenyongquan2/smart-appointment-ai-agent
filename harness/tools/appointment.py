"""create_appointment 工具：薄封装 AppointmentService.save_appointment。

这是整套工具里唯一的「写操作」——会落库、产生真实副作用，因此标了 dangerous=True
（见文件末尾）。其它工具都是只读查询。薄封装的精髓在这个文件里体现得最清楚：本模块
只负责「把校验过的入参翻译成 service 能吃的形状、再转交出去」，不写任何业务规则
（档期冲突、价格、技师匹配等全在 services/ 里）。
"""

from __future__ import annotations

from harness.tools.base import Tool
from harness.tools.schemas import CreateAppointmentArgs
from harness.tools.time_utils import resolve_time_window


async def _handler(args: CreateAppointmentArgs) -> dict[str, object]:
    # 延迟 import（放在函数体内而非模块顶部）：仅在真正调用本工具时才拉起
    # AppointmentService（它会连 DB），避免「一导入工具模块就触发重型依赖加载」。
    from services.appointment_service import AppointmentService

    # ① 把「起始时间字符串 + 时长字符串」换算成具体的 (start, end) 时间窗。
    #    args.start_time 形如 "2026-06-19 14:00"，args.duration 形如 "60分钟"。
    #    解析失败（格式非法/未知）会返回 None——这是工具层唯一做的「输入兜底」，
    #    不是业务逻辑：让 LLM 拿到一句人话错误，下一轮自行补正参数。
    window = resolve_time_window(args.start_time, args.duration)
    if window is None:
        return {"success": False, "error": "时间或时长格式非法，无法创建预约。"}

    start, end = window  # 两个 datetime 对象，service 需要的是 datetime 而非字符串
    # ② 组装 service 期望的 appointment_history 字典（即把入参原样打包）。
    #    注意这里只是「换形状」——没有任何挑选/校验/计算，纯转交。
    appointment_history = {
        "start_time": args.start_time,
        "duration": args.duration,
        "project": args.project,
        "technician_id": args.technician_id,
    }
    service = AppointmentService()
    # ③ 真正的写库动作全部委托给 service.save_appointment——本工具不碰 DB 细节。
    #    易误解点：technician_id 在 schema 里是 int，但 service 这里要 str，故显式 str()。
    success = service.save_appointment(
        technician_id=str(args.technician_id),
        start_time=start,
        end_time=end,
        appointment_history=appointment_history,
        session_id=args.session_id,  # 用 session_id 隔离/记录，是哪次会话下的单
    )
    # ④ 回给 LLM 的结果只保留它后续表述所需的最小字段（成功与否 + 关键回显）。
    #    bool(success)：service 可能返回真值/假值而非严格 bool，这里规整成 True/False。
    return {
        "success": bool(success),
        "technician_id": args.technician_id,
        "start_time": args.start_time,
    }


# 工具对象声明四要素（name/description/args_schema/handler）+ dangerous 标志。
# description 是写给「模型」看的说明书：决定 LLM 在什么情形下选择调用本工具。
create_appointment = Tool(
    name="create_appointment",
    description=(
        "为指定技师在某个时间窗创建预约并落库。仅在已确认技师可用、信息齐全时调用。"
        "返回 {success: bool}。"
    ),
    args_schema=CreateAppointmentArgs,
    handler=_handler,
    # dangerous=True：这是「危险工具」。为何危险——它写库、不可幂等（重试会重复下单）、
    # 一旦执行就产生真实业务后果。因此 agent loop 分发前会过一道「权限闸门」
    # （harness/guardrails/permission），由它决定放行/拦截/需人工确认；只读查询工具
    # 用默认 dangerous=False，直接放行。这也是为何 loop 的 _dispatch 对工具「绝不重试」。
    dangerous=True,  # 写库的副作用操作，分发前须经权限闸门（Phase 5）
)
