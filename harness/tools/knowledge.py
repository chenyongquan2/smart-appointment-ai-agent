"""search_knowledge 工具：薄封装 KnowledgeService.search。"""

from __future__ import annotations

from typing import Any

from harness.tools.base import Tool
from harness.tools.schemas import SearchKnowledgeArgs


# handler 收到的 args 已是「被 SearchKnowledgeArgs 校验过」的强类型实例（Tool.run 里完成），
# 故这里可直接 args.query / args.top_k 访问，无需再做存在性/类型检查。
async def _handler(args: SearchKnowledgeArgs) -> list[dict[str, Any]]:
    # 延迟 import，避免加载工具模块即拉起重型 service / 索引。
    from services.knowledge_service import KnowledgeService

    # 这就是「工具是 services/ 的薄封装」：工具自身不写检索逻辑，只负责把已校验的参数
    # 转交给 KnowledgeService。真正的 SQLite+FAISS 检索都在 service 里（本层不重写业务逻辑）。
    service = KnowledgeService()
    # 懒初始化：service 未建好索引时先 initialize（getattr 容错——属性不存在按 False 处理，
    # 即也会初始化）。注意这是「方法内每次都 new 一个 service」，并非全局单例。
    if not getattr(service, "initialized", False):
        await service.initialize()
    # 参数映射：把校验后的 args 字段一一转交 service.search；工具层到此结束，不加工返回值。
    return await service.search(args.query, top_k=args.top_k, category=args.category)


# 模块级单例：这一个 Tool 实例会被 build_default_registry 直接注册、复用。
# 它把「四要素」凑齐——名字 / 给模型的说明 / 入参 schema / 上面的 handler。
search_knowledge = Tool(
    name="search_knowledge",
    description=(
        # 这段话会进 tools schema 给 LLM 看：既说「这工具能干啥」，也点明「何时该用」
        # （咨询信息而非直接预约），引导模型在对话里恰当地触发它。
        "在门店知识库中检索与用户问题最相关的文档（服务项目、价格、营业时间、"
        "注意事项等）。当用户在咨询信息而非直接预约时使用。返回按相关度排序的文档列表。"
    ),
    args_schema=SearchKnowledgeArgs,
    handler=_handler,
    # 未传 dangerous → 取默认 False：纯只读检索，分发时跳过权限闸门。
)
