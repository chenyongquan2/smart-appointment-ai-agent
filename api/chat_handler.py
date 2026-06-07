"""请求编排入口（Phase 3）。

由 harness 的 TAO 循环（``AgentLoop``）驱动，取代旧的「LLM 分类 + if/else 硬路由」
（``ClassificationProcessor`` / ``AgentRouter`` 已退役，文件保留以便回滚）。

对外保留 ``ProcessUserInput_stream`` 的签名与异步流式 ``yield`` 接口，前端
（web/templates/index.html）按 ``[THOUGHT]`` / ``[REPLY]`` 前缀渲染，调用方无需改动。
"""

import uuid

from config.model_provider import create_chat_model
from harness.runtime import AgentLoop
from harness.tools.registry import build_default_registry

# 全局 session_id 用于单用户场景（按 session 隔离留待 Phase 4）。
global_session_id = str(uuid.uuid4())

# 模块级单例：注册工具、创建 LLM、构造 loop（绑定工具 schema 一次即可）。
_registry = build_default_registry()
_agent_loop = AgentLoop(llm=create_chat_model(temperature=0), registry=_registry)


async def ProcessUserInput_stream(user_input, state=None, context=None):
    """
    user_input: 用户输入
    state: 兼容旧签名（当前由 loop 自主决策，不再依赖外部状态机）
    context: 兼容旧签名（多轮上下文留待 Phase 4 的会话记忆）
    返回: 异步流式 yield 文本（带 [THOUGHT]/[REPLY] 前缀供前端渲染）
    """
    async for token in _agent_loop.run(user_input, session_id=global_session_id):
        yield token
