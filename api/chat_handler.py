"""请求编排入口（Phase 4：状态与记忆）。

由 harness 的 TAO 循环（``AgentLoop``）驱动，并按 ``session_id`` 隔离会话状态与
分层记忆：

- **会话隔离**：``SessionStore`` 按 ``session_id`` 持有独立历史，取代 Phase 3 的
  全局 ``global_session_id`` + 模块级单例状态（黄金准则：会话隔离）。
- **短期记忆**：``ShortTermMemory`` 把会话最近 N 轮历史注入 ``AgentLoop``。
- **长期记忆**：``LongTermMemory`` 跨会话读取用户偏好，作为系统提示补充。
- **持久化**：历史经 ``ConversationRepository`` 落 SQLite，进程重启可恢复。

``AgentLoop`` 保持无状态（只读历史、产出回复）；本模块负责取/建会话、注入记忆、
回写历史。对外保留 ``ProcessUserInput_stream`` 的异步流式 ``yield`` 与
``[THOUGHT]`` / ``[REPLY]`` / ``[ERROR]`` 前缀语义，前端无需改动既有解析。
"""

import uuid
from typing import Optional, Tuple

from config.model_provider import create_chat_model
from db.db_router import DatabaseRouter
from harness.memory.long_term import LongTermMemory
from harness.memory.short_term import ShortTermMemory
from harness.runtime import AgentLoop
from harness.runtime.session import SessionStore
from harness.tools.registry import build_default_registry

# 模块级单例：注册工具、创建 LLM、构造（无状态的）loop。
_registry = build_default_registry()
_agent_loop = AgentLoop(llm=create_chat_model(temperature=0), registry=_registry)

# 持久化与记忆组件（DatabaseRouter 复用既有 SQLite + Repository）。
_db = DatabaseRouter()
_session_store = SessionStore(repo=_db.conversations)
_short_term = ShortTermMemory(window_turns=10)
_long_term = LongTermMemory(repo=_db.user_behavior)

_REPLY_PREFIX = "[REPLY]"


async def ProcessUserInput_stream(
    user_input,
    state=None,
    context=None,
    session_id: Optional[str] = None,
):
    """处理一轮用户输入，按会话隔离地驱动 harness 并流式产出回复。

    Args:
        user_input: 用户输入。
        state / context: 兼容旧签名（会话状态现由 ``session_id`` + ``SessionStore``
            管理，这两个参数保留但不再使用）。
        session_id: 会话标识；缺省时本函数生成一个新的（调用方可通过
            ``resolve_session_id`` 预先确定以便回传给前端）。

    Yields:
        带 ``[THOUGHT]`` / ``[REPLY]`` 前缀的文本片段。
    """
    sid = session_id or str(uuid.uuid4())
    session = _session_store.get_or_create(sid)

    # 注入的历史 = 本轮之前的回合（当前 user_input 单独传给 loop，勿重复注入）。
    history_msgs = _short_term.to_messages(session.history)
    preference_hint = _long_term.build_preference_hint(session.user_id)

    # 先把本轮用户输入写入会话（内存窗口 + 持久化）。
    _session_store.append_turn(sid, "user", user_input)

    reply_text = ""
    async for token in _agent_loop.run(
        user_input,
        session_id=sid,
        history=history_msgs,
        system_suffix=preference_hint,
    ):
        if token.startswith(_REPLY_PREFIX):
            reply_text = token[len(_REPLY_PREFIX):]
        yield token

    # 回写助手回复（兜底回复同样记入历史，保证多轮连续）。
    if reply_text:
        _session_store.append_turn(sid, "assistant", reply_text)


def resolve_session_id(session_id: Optional[str]) -> str:
    """返回应使用的 session_id：沿用传入值，缺省时生成新值。

    供 Channel 层在响应前确定 session_id 并回传给前端（如响应头 X-Session-Id），
    使后续请求能带回同一会话。
    """
    return session_id or str(uuid.uuid4())
