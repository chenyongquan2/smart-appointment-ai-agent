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

from langchain_core.messages import SystemMessage

from config.model_provider import create_chat_model
from db.db_router import DatabaseRouter
from harness.memory.long_term import LongTermMemory
from harness.memory.short_term import ShortTermMemory
from harness.memory.summary import LLMSummaryMemory
from harness.runtime import AgentLoop
from harness.runtime.session import SessionStore
from harness.runtime.system_prompt import build_system_prompt
from harness.subagents import build_default_subagent_registry, build_delegate_tool
from harness.tools.registry import ToolRegistry, build_default_registry

# 模块级单例（Phase 7）：
# 这些对象在「import 本模块时」只建一次，被所有请求共享——故必须无状态/可并发复用
# （会话隔离靠下面的 session_id + SessionStore，而不是给每个用户各建一套对象）。
# - 全量工具 registry：领域工具仍在此注册，但由子 Agent 经其工具子集调用。
# - 子 Agent registry：预约 / 咨询 / 行为分析三个专员。
# - delegate 工具：主 Agent 据此自主派生子 Agent（取代硬编码路由）。
# - 主 registry 只含 delegate：主 Agent 负责「决策派给谁」，不直接执行领域工具。
_llm = create_chat_model(temperature=0)  # temperature=0：尽量确定性，利于评估对照与复现
_full_registry = build_default_registry()
_subagents = build_default_subagent_registry()
_delegate_tool = build_delegate_tool(_llm, _full_registry, _subagents)

# ★ 关键设计：主 registry 里「只放 delegate 这一个工具」。
#   于是主 Agent 的唯一动作就是「调 delegate(派给哪个专员)」——它只做路由决策，
#   真正干活的领域工具都藏在子 Agent 的工具子集里。对比 Phase 7 之前的硬编码 if/else 路由，
#   这把「派给谁」交还给模型自主判断。
_main_registry = ToolRegistry()
_main_registry.register(_delegate_tool)

_agent_loop = AgentLoop(
    llm=_llm,
    registry=_main_registry,
    # 主 Agent 专用系统提示：把可委派的子 Agent 清单写进去，模型才知道能派给谁。
    system_prompt=build_system_prompt(_main_registry, _subagents),
)

# 持久化与记忆组件（DatabaseRouter 复用既有 SQLite + Repository）。
_db = DatabaseRouter()
_WINDOW_TURNS = 10                                           # 短期记忆窗口的大小：保留最近多少条消息（单位=条消息，一问一答=两条；压缩窗外边界与此一致）
_session_store = SessionStore(repo=_db.conversations)       # 按 session_id 隔离会话历史
_short_term = ShortTermMemory(window_turns=_WINDOW_TURNS)    # 短期记忆：只回放最近 10 轮
_long_term = LongTermMemory(repo=_db.user_behavior)          # 长期记忆：跨会话的用户偏好
# 摘要记忆（记忆压缩）：窗外较旧回合滚动压缩为摘要，下一轮注入。读/写分离——
# 写侧在回合收尾算（不挡关键路径），读侧请求开始时纯读缓存。窗口轮数与短期记忆一致。
_summary = LLMSummaryMemory(
    llm=_llm,
    conversations_repo=_db.conversations,
    summaries_repo=_db.summaries,
    window_turns=_WINDOW_TURNS,
)

# 与 AgentLoop 的约定前缀：loop 把「最终回复」以 [REPLY]... 形式 yield 出来，
# 本模块据此从一串 token 里择出真正的回复文本（其余如 [THOUGHT] 是过程，不回写历史）。
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
    # ════════════════════════════════════════════════════════════════════
    # 一条消息的完整路径（这就是本文件的主线，按 ①→⑥ 读）
    # ════════════════════════════════════════════════════════════════════

    # ① 会话隔离：定位「这条消息属于哪个会话」。缺 session_id 就新开一个会话。
    #    get_or_create 据此取/建对应会话——不同 session_id 的历史互不串扰。
    sid = session_id or str(uuid.uuid4())
    session = _session_store.get_or_create(sid)

    # ② 记忆注入（在「写入本轮输入之前」先取历史，避免把当前这句也当成历史回放）：
    #    - 短期：把最近 N 轮历史转成 BaseMessage 列表，喂给 loop 当上下文。
    #    - 长期：跨会话的用户偏好，作为「系统提示补充」（system_suffix）。
    history_msgs = _short_term.to_messages(session.history)
    preference_hint = _long_term.build_preference_hint(session.user_id)

    #    - 摘要（记忆压缩）：读侧纯读上一轮预算好的摘要缓存（不调 LLM）。非空则作为独立
    #      SystemMessage 置于 history 首条——落在「系统提示之后、短期窗口之前」，与长期偏好
    #      （走 system_suffix）物理分开。摘要承载被短期窗口裁掉的早期约束/未完成槽位。
    summary_hint = _summary.get_summary_hint(sid)
    if summary_hint:
        history_msgs = [SystemMessage(content=summary_hint)] + history_msgs

    # ③ 先写「用户输入」入会话（内存窗口 + 持久化 SQLite）。
    #    注意：必须在 ② 取完历史「之后」再写，否则当前这句会污染本轮注入的历史。
    _session_store.append_turn(sid, "user", user_input)

    # ④ 驱动 TAO 循环。user_input 单独作参数传入（已在 history_msgs 里排除，勿重复注入）。
    #    run(...) 是异步生成器：会逐个 yield 出 token（[THOUGHT].../[REPLY]...）。
    reply_text = ""
    async for token in _agent_loop.run(
        user_input,
        session_id=sid,
        history=history_msgs,          # 短期记忆
        system_suffix=preference_hint, # 长期偏好，拼到系统提示末尾
    ):
        # ⑤ 一边把每个 token 透传给前端（保留流式体验），一边「截留」最终回复：
        #    只有 [REPLY] 前缀那条是要回写历史的真正回复；切掉前缀后存进 reply_text。
        #    （若 loop 多次发 [REPLY]，这里以最后一条为准。）
        if token.startswith(_REPLY_PREFIX):
            reply_text = token[len(_REPLY_PREFIX):]
        yield token

    # ⑥ 回写「助手回复」入会话，至此本轮一问一答都已落库，下一轮才能续上多轮上下文。
    #    （兜底回复——如 loop 跑满步数的那句——同样记入，保证历史不断档。）
    if reply_text:
        _session_store.append_turn(sid, "assistant", reply_text)

    # ⑦ 写侧记忆压缩（inline-after-stream）：回复已流式送达，此处趁收尾把「下一轮要用的」
    #    摘要算好落库——LLM 调用移出关键路径、不卡首 token；inline（非 fire-and-forget）
    #    保证确定性完成与可观测。失败已在内部降级（不写缓存、不抛），不影响本轮。
    await _summary.compact_if_needed(sid)


def resolve_session_id(session_id: Optional[str]) -> str:
    """返回应使用的 session_id：沿用传入值，缺省时生成新值。

    供 Channel 层在响应前确定 session_id 并回传给前端（如响应头 X-Session-Id），
    使后续请求能带回同一会话。
    """
    return session_id or str(uuid.uuid4())
