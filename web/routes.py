"""
Web界面路由

处理前端页面渲染和聊天功能
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from api.chat_handler import chat_stream, resolve_session_id
import logging

# 创建logger实例
logger = logging.getLogger(__name__)
# 模板配置
templates = Jinja2Templates(directory="web/templates")

# Web路由器
router = APIRouter(tags=["Web界面"])

class ChatRequest(BaseModel):
    message: str
    state: str | None = None
    session_id: str | None = None  # 缺省时服务端生成并经 X-Session-Id 回传

@router.get("/", response_class=HTMLResponse, summary="主页")
async def read_root(request: Request):
    """渲染主页聊天界面"""
    return templates.TemplateResponse("index.html", {"request": request})

@router.post("/chat/stream", summary="流式聊天")
async def chat_stream_endpoint(chat: ChatRequest):
    """处理流式聊天请求（按 session_id 隔离会话；响应头回传 X-Session-Id）

    经 executor 的同步内联模式执行（`chat_stream`）——与飞书路径共享同一套并发记账，
    但 token 流仍在本请求协程内直接透传，对外行为与改造前一致。
    """
    session_id = resolve_session_id(chat.session_id)

    async def token_generator():
        async for token in chat_stream(chat.message, session_id=session_id):
            yield token
    return StreamingResponse(
        token_generator(),
        media_type="text/plain",
        headers={"X-Session-Id": session_id},
    )

@router.post("/chat", summary="兼容性聊天接口")
async def chat_endpoint(chat: ChatRequest):
    """兼容性聊天接口，建议使用/chat/stream"""
    session_id = resolve_session_id(chat.session_id)

    async def token_generator():
        async for token in chat_stream(chat.message, session_id=session_id):
            yield token
    return StreamingResponse(
        token_generator(),
        media_type="text/plain",
        headers={"X-Session-Id": session_id},
    )

@router.get("/user_behavior", response_class=HTMLResponse, summary="用户行为分析页面")
async def user_behavior_page(request: Request):
    """用户行为分析页面"""
    return templates.TemplateResponse("user_behavior_analysis.html", {"request": request})

@router.get("/technician", response_class=HTMLResponse, summary="技师状态页面")
async def technician_page(request: Request):
    """技师状态页面"""
    # 通过API层获取技师数据
    try:
        from api.technician import get_all_technicians
        
        # 调用API层函数获取数据
        technicians = await get_all_technicians()
        
        return templates.TemplateResponse("technician.html", {
            "request": request,
            "technicians": technicians
        })
    except Exception as e:
        return templates.TemplateResponse("technician.html", {
            "request": request,
            "technicians": [],
            "error": str(e)
        })

@router.get("/technician_schedule", response_class=HTMLResponse, summary="技师排班页面")
async def technician_schedule_page(request: Request):
    """技师排班页面"""
    try:
        from api.technician import get_all_technicians_schedule_today
        from config.time_config import time_config
        
        # 获取当前日期
        current_date = time_config.current_date_str()
        
        # 通过API层获取所有技师的排班数据
        schedules_data = await get_all_technicians_schedule_today()
        
        # 构建排班数据格式 - 直接使用API返回的数据
        schedule = []
        for schedule_item in schedules_data:
            schedule.append({
                "id": schedule_item["technician_id"],
                "name": schedule_item["technician_name"],
                "busy_periods": schedule_item["busy_periods"]
            })
        
        return templates.TemplateResponse("technician_schedule.html", {
            "request": request,
            "schedule": schedule,
            "current_date": current_date
        })
    except Exception as e:
        logger.error(f"加载技师排班数据失败: {str(e)}")
        return templates.TemplateResponse("technician_schedule.html", {
            "request": request,
            "schedule": [],
            "error": str(e)
        })

@router.get("/user_behavior_analysis", response_class=HTMLResponse, summary="用户行为分析页面")
async def user_behavior_analysis_page(request: Request):
    """用户行为分析页面"""
    return templates.TemplateResponse("user_behavior_analysis.html", {"request": request})

@router.get("/admin", response_class=HTMLResponse, summary="系统管理页面")
async def admin_dashboard(request: Request):
    """系统管理仪表板"""
    try:
        # 通过API层获取系统状态信息
        from api.technician import get_all_technicians

        # 获取技师数据
        technicians = await get_all_technicians()

        # 数据库信息（知识库已随本地 RAG 移除，见 change: remove-local-rag）
        db_info = {
            "technicians_count": len(technicians),
        }
        
        return templates.TemplateResponse("admin_dashboard.html", {
            "request": request,
            "db_info": db_info,
            "technicians": technicians[:5]  # 只显示前5个技师
        })
    except Exception as e:
        return templates.TemplateResponse("admin_dashboard.html", {
            "request": request,
            "db_info": {},
            "technicians": [],
            "error": str(e)
        })

@router.get("/admin/database", response_class=HTMLResponse, summary="数据库管理页面")
async def database_admin_page(request: Request):
    """数据库管理页面"""
    try:
        # 通过API层获取数据库统计信息
        from api.technician import get_all_technicians

        # 获取技师数据
        technicians = await get_all_technicians()

        stats = {
            "technicians": len(technicians),
            "appointments": 0  # TODO: 通过API获取预约数量
        }
        
        return templates.TemplateResponse("database_admin.html", {
            "request": request,
            "stats": stats
        })
    except Exception as e:
        return templates.TemplateResponse("database_admin.html", {
            "request": request,
            "stats": {},
            "error": str(e)
        })
