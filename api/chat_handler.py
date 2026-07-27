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

import asyncio
import logging
import os
import uuid
from typing import Any, Callable, List, Optional, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from config.model_provider import create_chat_model
from db.db_router import DatabaseRouter
from executor import Task, TaskExecutor
from executor.local import TIMEOUT_REPLY
from harness.memory.long_term import LongTermMemory
from harness.memory.short_term import ShortTermMemory
from harness.memory.summary import LLMSummaryMemory
from harness.observability.file_exporter import FileSpanExporter
from harness.observability.sampling_exporter import SamplingSpanExporter
from harness.observability.tracer import Tracer
from harness.runtime import AgentLoop
from harness.runtime.agent_loop import RunOutcome
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

# 在线评估闭环（改造 7）：把真实对话 trace 落盘，作为 triage 的 trace 源。
# - 一个进程一个 trace 文件（run_id=进程级 uuid），主 loop 与子 Agent 共用同一 tracer，
#   故主/子 span 都进同一文件（子 Agent 各自开 root span，trace_id 不同——triage 按 trace_id 分组）。
# - 采样：默认全量（sample_rate=1.0）；命中失控信号的 trace 必留（不受采样率影响，见 SamplingSpanExporter）。
#   采样率经 EVAL_TRACE_SAMPLE_RATE 环境变量调（缺省 1.0）。
# - tracer 经 build_delegate_tool(..., tracer=) 透传子 Agent（盲区修复，与 evals/agent_capture.py 同款接法）。
_trace_sample_rate = float(os.getenv("EVAL_TRACE_SAMPLE_RATE", "1.0"))
_trace_exporter = SamplingSpanExporter(
    FileSpanExporter(run_id=uuid.uuid4().hex),
    sample_rate=_trace_sample_rate,
)
_tracer = Tracer(_trace_exporter)

_delegate_tool = build_delegate_tool(_llm, _full_registry, _subagents, tracer=_tracer)

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
    tracer=_tracer,  # 改造 7：主 loop 的 trace 落盘（含 root span 的 user_input/session_id）
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

logger = logging.getLogger(__name__)

# 与 AgentLoop 的约定前缀：loop 把「最终回复」以 [REPLY]... 形式 yield 出来，
# 本模块据此从一串 token 里择出真正的回复文本（其余如 [THOUGHT] 是过程，不回写历史）。
_REPLY_PREFIX = "[REPLY]"

# 本轮被中断（墙钟超时 / 客户端断连）时补写进历史的兜底回合默认文案。
# 调用方（executor）会传入与实际投递给用户的一致的文案覆盖它。
_DEFAULT_INTERRUPTED_REPLY = "（上一轮处理被中断，未能完成回复。）"


def _turns_to_messages(turns: List[Any]) -> List[BaseMessage]:
    """把回合（dict 含 role/content）转成 LangChain 消息列表；未知 role 跳过。

    供读侧把 ``get_read_context`` 返回的「未覆盖原文回合」注入上下文
    （change: fix-compaction-gap-blindspot）。
    """
    msgs: List[BaseMessage] = []
    for t in turns:
        role, content = t.get("role"), t.get("content", "")
        if role == "user":
            msgs.append(HumanMessage(content=content))
        elif role == "assistant":
            msgs.append(AIMessage(content=content))
    return msgs


async def ProcessUserInput_stream(
    user_input,
    state=None,
    context=None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    on_outcome: Optional[Callable[[RunOutcome], None]] = None,
    interrupted_reply: str = _DEFAULT_INTERRUPTED_REPLY,
):
    """处理一轮用户输入，按会话隔离地驱动 harness 并流式产出回复。

    Args:
        user_input: 用户输入。
        state / context: 兼容旧签名（会话状态现由 ``session_id`` + ``SessionStore``
            管理，这两个参数保留但不再使用）。
        session_id: 会话标识；缺省时本函数生成一个新的（调用方可通过
            ``resolve_session_id`` 预先确定以便回传给前端）。
        user_id: 提交者标识，用于长期偏好按人隔离。群聊场景 MUST 传（否则全群成员的
            偏好会混作同一个 ``default_user``）；``None`` 时沿用默认用户，Web 行为不变。
        on_outcome: 透传给 ``AgentLoop.run`` 的带外结束方式回调，供调用方区分「答完了」
            与「被护栏拦停」（两者的回复文本无法分辨）。
        interrupted_reply: 本轮被中断时补写进历史的兜底回合文案；由调用方传入与实际
            投递给用户的一致的文案。

    Yields:
        带 ``[THOUGHT]`` / ``[REPLY]`` 前缀的文本片段。
    """
    # ════════════════════════════════════════════════════════════════════
    # 一条消息的完整路径（这就是本文件的主线，按 ①→⑥ 读）
    # ════════════════════════════════════════════════════════════════════

    # ① 会话隔离：定位「这条消息属于哪个会话」。缺 session_id 就新开一个会话。
    #    get_or_create 据此取/建对应会话——不同 session_id 的历史互不串扰。
    sid = session_id or str(uuid.uuid4())
    # user_id 决定「读谁的长期偏好」。群聊里同一会话由多人共享——历史该共享，偏好不该，
    # 故由 Channel 层把发送者身份传下来；Web 不传，沿用默认用户（行为不变）。
    session = _session_store.get_or_create(sid, user_id=user_id)

    # ② 记忆注入（在「写入本轮输入之前」先取历史，避免把当前这句也当成历史回放）：
    #    - 长期：跨会话的用户偏好，作为「系统提示补充」（system_suffix）。
    preference_hint = _long_term.build_preference_hint(session.user_id)

    #    - 短期 + 摘要（记忆压缩，无盲区，fix-compaction-gap-blindspot）：
    #      可见性分界 = covered_upto——摘要(id≤covered_upto) 作独立 SystemMessage 置 history 首条，
    #      其后接「全部未覆盖原文(id>covered_upto)」。没进摘要的一律保留原文 → 不存在「掉出窗口
    #      又没进摘要」的夹缝盲区。窗外原文条数有界（≈window+min_old），不会无界膨胀。
    try:
        summary_text, uncovered = _summary.get_read_context(sid)
        history_msgs = _turns_to_messages(uncovered)
        if summary_text:
            history_msgs = [SystemMessage(content=summary_text)] + history_msgs
    except Exception:  # noqa: BLE001 —— 持久层抖动等：退回旧路径（短期窗口 + 摘要 hint）
        logger.warning("读侧 get_read_context 失败，退回短期窗口兜底", exc_info=True)
        history_msgs = _short_term.to_messages(session.history)
        summary_hint = _summary.get_summary_hint(sid)
        if summary_hint:
            history_msgs = [SystemMessage(content=summary_hint)] + history_msgs

    # ③ 先写「用户输入」入会话（内存窗口 + 持久化 SQLite）。
    #    注意：必须在 ② 取完历史「之后」再写，否则当前这句会污染本轮注入的历史。
    _session_store.append_turn(sid, "user", user_input)

    # ④ 驱动 TAO 循环。user_input 单独作参数传入（已在 history_msgs 里排除，勿重复注入）。
    #    run(...) 是异步生成器：会逐个 yield 出 token（[THOUGHT].../[REPLY]...）。
    reply_text = ""
    try:
        async for token in _agent_loop.run(
            user_input,
            session_id=sid,
            history=history_msgs,          # 短期记忆
            system_suffix=preference_hint, # 长期偏好，拼到系统提示末尾
            on_outcome=on_outcome,         # 带外结束方式（供 executor 判定终态）
        ):
            # ⑤ 一边把每个 token 透传给前端（保留流式体验），一边「截留」最终回复：
            #    只有 [REPLY] 前缀那条是要回写历史的真正回复；切掉前缀后存进 reply_text。
            #    （若 loop 多次发 [REPLY]，这里以最后一条为准。）
            if token.startswith(_REPLY_PREFIX):
                reply_text = token[len(_REPLY_PREFIX):]
            yield token
    except (asyncio.CancelledError, GeneratorExit):
        # ★ 中断路径（墙钟超时把 CancelledError 抛进来，或客户端断连触发 GeneratorExit）。
        #   ③ 已经把 user 回合写进库了，若就这么走人，历史里会留下一条永远配不上回复的
        #   孤立 user 回合——而「历史成对」是 ShortTermMemory 与摘要压缩的隐含前提，破了
        #   它下一轮模型会看到一句没人回的话，用户重问后还会出现连排的重复 user 消息。
        #   故先补一条兜底 assistant 回合。这里只做同步 DB 写、不 await（GeneratorExit
        #   期间不允许挂起）。
        _session_store.append_turn(sid, "assistant", reply_text or interrupted_reply)
        # 必须重抛：吞掉取消信号会让 executor 把被中断的任务误判为正常完成。
        raise

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


# ════════════════════════════════════════════════════════════════════════════
# 任务执行层接线（change: feishu-channel-integration）
# 依赖方向：channels/ → executor/ → 本模块 → harness/。executor 不反向依赖任何
# Channel 或编排实现——runner 是注入进去的，故换 IM 平台时这一层零改动。
# ════════════════════════════════════════════════════════════════════════════
def _runner(task: Task, on_outcome: Callable[[RunOutcome], None]):
    """把一个 Task 翻译成本模块的编排调用。executor 只认这个协议。"""
    return ProcessUserInput_stream(
        task.user_input,
        session_id=task.session_id,
        user_id=task.user_id,
        on_outcome=on_outcome,
        # 中断时补写进历史的兜底回合，与 delivery 实际投递给用户的文案取同一份常量。
        interrupted_reply=TIMEOUT_REPLY,
    )


executor = TaskExecutor(
    _runner,
    max_concurrency=int(os.getenv("EXECUTOR_MAX_CONCURRENCY", "10")),
    max_queue_per_session=int(os.getenv("EXECUTOR_MAX_QUEUE_PER_SESSION", "5")),
    wall_clock_timeout=float(os.getenv("EXECUTOR_WALL_CLOCK_TIMEOUT", "600")),
)

# 应急回退开关：默认走新路径（默认关的话新路径永远没人跑，等于没上线）。
_EXECUTOR_ENABLED = os.getenv("EXECUTOR_ENABLED", "true").strip().lower() not in {
    "0", "false", "no", "off",
}


def chat_stream(
    user_input: str,
    session_id: str,
    user_id: Optional[str] = None,
):
    """Web 入口：经 executor 的**同步内联模式**执行，逐 token 透传。

    内联而非入队，是为了让「Web 对外行为不变」在构造上成立——透传的还是同一个 async
    generator，没有跨协程队列，因而不存在背压、断连歧义与异常重抛（见 executor 模块
    docstring）。它仍与飞书路径共享同一套并发记账（同会话串行、全局并发上限）。
    """
    if not _EXECUTOR_ENABLED:
        # 应急回退：绕过 executor 直调编排层（改造前的老路径）。
        return ProcessUserInput_stream(user_input, session_id=session_id, user_id=user_id)
    return executor.execute_inline(
        Task(session_id=session_id, user_input=user_input, user_id=user_id, channel="web")
    )
