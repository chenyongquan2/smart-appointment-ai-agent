"""search_knowledge 工具：薄封装知识库检索端口。

原先直连 ``KnowledgeService``（本地 SQLite+FAISS）；本地 RAG 已于 change
``remove-local-rag`` 移除，改为依赖 ``services/knowledge_search.py`` 的可替换端口。
工具的四要素（name / description / args_schema / dangerous）**一字未改**——这正是
「换检索实现时工具层一行都不用动」这条设计主张的兑现，故上层的 registry 注册、
子 Agent 工具切片、评估用例标注全都无需跟着改。
"""

from __future__ import annotations

from typing import Any

from harness.tools.base import Tool
from harness.tools.schemas import SearchKnowledgeArgs


# handler 收到的 args 已是「被 SearchKnowledgeArgs 校验过」的强类型实例（Tool.run 里完成），
# 故这里可直接 args.query / args.top_k 访问，无需再做存在性/类型检查。
async def _handler(args: SearchKnowledgeArgs) -> list[dict[str, Any]]:
    # 延迟 import，避免加载工具模块即拉起端口背后的实现（未来是远程 RAG client）。
    from services.knowledge_search import get_knowledge_search

    # 「薄封装」的极致形态：解析当前端口 + 转交已校验的参数，到此为止。
    # 每次调用都重新 get（而非模块加载时取一次），故运行中注入的实现能即时生效。
    #
    # 未接入任何实现时，缺省端口会抛 KnowledgeBackendNotConfigured——不在这里 catch：
    # agent loop 的 _dispatch 会把它吞成「工具执行失败（search_knowledge）：…」回灌给模型，
    # loop 继续。刻意不降级成空列表，否则模型会当成「库里没有」而编造答案（见 design D2）。
    port = get_knowledge_search()
    return await port.search(args.query, top_k=args.top_k, category=args.category)


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
