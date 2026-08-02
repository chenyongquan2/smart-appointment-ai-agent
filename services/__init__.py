"""
业务服务层模块

包含：
- 知识库检索端口（本地 RAG 已移除，待接入独立 RAG 项目）
- 技师服务
- 预约服务
- 用户行为服务
- 推荐调度服务
- 文本嵌入工具（现服务于技师专长相似度匹配）
"""

from .text_embedding import (
    aembed_input,
    embed_input,
    find_best_match_indices,
    save_technician_embeddings,
    load_technician_embeddings
)
from .knowledge_search import (
    KnowledgeBackendNotConfigured,
    KnowledgeSearchPort,
    get_knowledge_search,
    set_knowledge_search,
)
from .technician_service import TechnicianService
from .appointment_service import AppointmentService
from .user_behavior_service import UserBehaviorService
from .recommendation_service import RecommendationService

__all__ = [
    'aembed_input',
    'embed_input',
    'find_best_match_indices',
    'save_technician_embeddings',
    'load_technician_embeddings',
    'KnowledgeBackendNotConfigured',
    'KnowledgeSearchPort',
    'get_knowledge_search',
    'set_knowledge_search',
    'TechnicianService',
    'AppointmentService',
    'UserBehaviorService',
    'RecommendationService'
]
