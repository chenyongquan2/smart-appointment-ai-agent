"""
简化的API模块

核心功能API；管理员功能已移至 scripts 目录。

注：原 `consultation`（pre-harness 咨询链路）与 `knowledge`（知识库管理）两个路由
已随本地 RAG 移除（change: remove-local-rag）——咨询能力现由 harness 的 consultant
子 Agent 承担，知识库内容将由独立的 RAG 项目提供。
"""

# 导入各业务模块的路由
from .appointment import router as appointment_router
from .technician import router as technician_router
from .user_behavior_analysis import router as user_behavior_analysis_router
from .user_behavior_analysis import router_underscore as user_behavior_analysis_underscore_router

# 创建API路由列表（用于注册到FastAPI应用）
api_routers = [
    appointment_router,
    technician_router,
    user_behavior_analysis_router,
    user_behavior_analysis_underscore_router
]
