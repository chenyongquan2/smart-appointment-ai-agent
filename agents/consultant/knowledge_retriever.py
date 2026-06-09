"""
知识检索器

负责从知识库中检索相关信息
"""

import logging
from typing import List, Dict, Any
from services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)


class KnowledgeRetriever:
    """知识检索器"""
    
    def __init__(self):
        self.knowledge_service = KnowledgeService()
        self.kb_initialized = False
    
    async def initialize(self):
        """初始化知识库服务"""
        if not self.kb_initialized:
            await self.knowledge_service.initialize()
            self.kb_initialized = True
            logger.info("咨询机器人知识库服务已初始化")
    
    async def search_knowledge(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """搜索相关知识"""
        # 确保知识库已初始化
        if not self.kb_initialized:
            await self.initialize()
        
        # 搜索相关知识
        relevant_docs = await self.knowledge_service.search(query, top_k=top_k)
        
        # 记录检索日志
        self._log_search_results(query, relevant_docs)
        
        return relevant_docs or []
    
    def _log_search_results(self, query: str, relevant_docs: List[Dict[str, Any]]):
        """记录搜索结果日志"""
        if relevant_docs:
            hits = [
                f"{i}. [相关度:{doc.get('score', 0):.3f}] "
                f"[分类:{doc.get('category', '未知')}] {doc.get('content', '')[:80]}..."
                for i, doc in enumerate(relevant_docs, 1)
            ]
            logger.debug(
                "知识库检索 (查询: '%s'): 共 %d 条相关知识\n%s",
                query, len(relevant_docs), "\n".join(hits),
            )
        else:
            logger.debug("知识库检索: 未找到与 '%s' 相关的知识", query)
