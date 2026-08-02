"""
FastAPI应用程序

主应用程序入口，配置中间件、路由和异常处理
自动初始化技师数据
"""
import sys

# Windows 中文环境控制台默认 gbk，无法编码日志里的 emoji（如 ✅），统一转为 UTF-8
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from services.technician_service import TechnicianService
from services.recommendation_service import RecommendationService
import logging
import asyncio

# 导入路由
from api import api_routers
from api.core.exceptions import api_exception_handler, general_exception_handler, BusinessException
from web import router as web_router

# 配置日志：结构化 JSON 输出（取代纯文本 basicConfig）
from config.logging_setup import setup_logging
setup_logging(level=logging.INFO)
logger = logging.getLogger(__name__)

async def initialize_system():
    """系统启动时自动初始化"""
    try:
        logger.info("🚀 正在初始化智能预约系统...")

        # 初始化技师服务
        logger.info("👨‍⚕️ 初始化技师服务...")
        technician_service = TechnicianService()
        technician_service.initialize_default_technicians()
        
        # 初始化推荐服务
        logger.info("🎯 启动推荐调度服务...")
        recommendation_service = RecommendationService()
        if recommendation_service.start_scheduler():
            logger.info("✅ 推荐调度服务启动成功")
        else:
            logger.warning("⚠️ 推荐调度服务启动失败")
        
        logger.info("✅ 系统初始化完成！")
        
    except Exception as e:
        logger.error(f"❌ 系统初始化失败: {e}")
        raise

def create_app() -> FastAPI:
    """创建FastAPI应用实例"""
    
    app = FastAPI(
        title="智能预约AI代理",
        description="提供预约管理、智能咨询、用户行为分析等功能的API服务",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc"
    )

    # 添加CORS中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境中应该设置具体的域名
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册异常处理器
    app.add_exception_handler(BusinessException, api_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)

    # 注册API路由
    for router in api_routers:
        app.include_router(router)

    # 注册Web界面路由
    app.include_router(web_router)

    # 静态文件
    app.mount("/static", StaticFiles(directory="web/static"), name="static")

    # 飞书长连接消费者（change: feishu-channel-integration）。
    # 与 Web 同进程，故与 executor / SessionStore 共用同一套模块级单例，SQLite 也保持
    # 单写者。⚠ 因此服务 MUST 单 worker 运行：多 worker 会起多份长连接、同一条消息被
    # 不同进程各消费一次，而事件去重表是进程内的，拦不住跨进程重复（= 重复下单）。
    feishu_consumer = {"instance": None}

    # 添加启动事件
    @app.on_event("startup")
    async def startup_event():
        """应用启动时自动初始化系统，并按开关启动飞书接入"""
        await initialize_system()

        # 用 chat_handler 里装配好的 executor 与 Repository，Channel 不自建这些对象。
        from api.chat_handler import channel_sessions, executor
        from channels.lark.consumer import build_consumer_from_env

        consumer = build_consumer_from_env(executor, channel_sessions)
        if consumer is not None:
            # start() 内部已收口异常、失败只返回 False——一个 Channel 起不来不该让
            # 整个 Web 服务也起不来。
            if await consumer.start():
                feishu_consumer["instance"] = consumer

    @app.on_event("shutdown")
    async def shutdown_event():
        """应用关闭时断开飞书长连接"""
        consumer = feishu_consumer.get("instance")
        if consumer is not None:
            await consumer.stop()

    return app

# 创建应用实例
app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
