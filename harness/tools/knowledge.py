"""search_knowledge 工具：薄封装 KnowledgeService.search。"""

from __future__ import annotations

from typing import Any

from harness.tools.base import Tool
from harness.tools.schemas import SearchKnowledgeArgs


async def _handler(args: SearchKnowledgeArgs) -> list[dict[str, Any]]:
    # 延迟 import，避免加载工具模块即拉起重型 service / 索引。
    from services.knowledge_service import KnowledgeService

    service = KnowledgeService()
    if not getattr(service, "initialized", False):
        await service.initialize()
    return await service.search(args.query, top_k=args.top_k, category=args.category)


search_knowledge = Tool(
    name="search_knowledge",
    description=(
        "在门店知识库中检索与用户问题最相关的文档（服务项目、价格、营业时间、"
        "注意事项等）。当用户在咨询信息而非直接预约时使用。返回按相关度排序的文档列表。"
    ),
    args_schema=SearchKnowledgeArgs,
    handler=_handler,
)
