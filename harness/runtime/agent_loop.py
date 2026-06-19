"""AgentLoop —— harness 运行时的 TAO（Thought→Action→Observation）循环（Phase 3）。

用 native tool calling 取代「LLM 分类一次 + if/else 硬路由」：每一步让绑定了工具
schema 的 LLM 推理，若返回工具调用就按名 dispatch 到 ``ToolRegistry``、把结果作为
tool message 喂回，循环迭代，直至模型产出最终文本回复或触达 ``max_steps`` 上限。

设计要点（见 openspec change phase-3-agent-loop 的 design.md）：
- 依赖注入 LLM（LangChain ``BaseChatModel``）与 ``ToolRegistry``，故可用 fake LLM
  做离线确定性单测，不触网。
- ``max_steps`` 防失控；工具失败回灌错误不崩；为 ``session_id`` 预留参数（会话隔离
  留待 Phase 4）；预留 ``on_tool_call`` / ``on_observation`` trace 钩子（落地留待 Phase 6）。
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Awaitable, Callable, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from harness.guardrails.budget import SpinDetector, estimate_tokens
from harness.guardrails.retry import (
    DEFAULT_BASE_DELAY,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_TIMEOUT,
    GuardrailExhausted,
    guarded_invoke,
)
from harness.observability.tracer import NoopTracer, Tracer
from harness.tools.registry import ToolRegistry
from harness.runtime.system_prompt import build_system_prompt

# 触达步数上限时的安全兜底回复（前端按 [REPLY] 前缀渲染）。
_FALLBACK_REPLY = "抱歉，本次处理步骤过多，暂时无法完成。请换种说法或稍后再试。"


class AgentLoop:
    """TAO 循环编排器。

    Args:
        llm: LangChain 聊天模型；MUST 支持 ``bind_tools``（真实 provider 经
            ``config.model_provider.create_chat_model`` 创建）。
        registry: 工具注册中心；提供 OpenAI tools schema 与按名 dispatch。
        max_steps: 单次请求的最大循环步数，防止死循环。
        max_tokens: 单次请求的累计 token 预算上限（近似估算）；``None`` 时禁用预算护栏。
        repeat_limit: 连续相同工具调用达到该次数即判定打转并终止；``None`` 时禁用。
        llm_timeout / llm_max_attempts / llm_base_delay: LLM 调用护栏参数（超时秒数、
            最大尝试次数、指数退避基准秒数），透传给 ``guarded_invoke``。
        retry_sleep: 退避等待实现（默认 ``asyncio.sleep``）；测试可注入 no-op。
        on_tool_call / on_observation: 可选 trace 钩子（默认 no-op）。
        tracer: 可选可观测 tracer（Phase 6）；注入时为整次 run 开 root span、每步开
            child span，记录 thought / tool_call / observation / latency / tokens。
            缺省为 ``NoopTracer``，行为与接入前完全一致（向后兼容）。
        system_prompt: 可选的系统提示覆盖（Phase 7）；子 Agent 用其专用提示构造
            ``AgentLoop`` 时传入。缺省为 ``None`` 时走 ``build_system_prompt(registry)``，
            与既有行为完全一致（向后兼容）。
    """

    def __init__(
        self,
        llm: BaseChatModel,
        registry: ToolRegistry,
        max_steps: int = 8,
        max_tokens: Optional[int] = None,
        repeat_limit: Optional[int] = 3,
        llm_timeout: float = DEFAULT_TIMEOUT,
        llm_max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        llm_base_delay: float = DEFAULT_BASE_DELAY,
        retry_sleep: Optional[Callable[[float], Awaitable[None]]] = None,
        on_tool_call: Optional[Callable[[dict[str, Any]], None]] = None,
        on_observation: Optional[Callable[[str, Any], None]] = None,
        tracer: Optional[Tracer] = None,
        system_prompt: Optional[str] = None,
    ) -> None:
        self.registry = registry
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.repeat_limit = repeat_limit
        self.llm_timeout = llm_timeout
        self.llm_max_attempts = llm_max_attempts
        self.llm_base_delay = llm_base_delay
        self._retry_sleep = retry_sleep
        self._on_tool_call = on_tool_call or (lambda call: None)
        self._on_observation = on_observation or (lambda name, result: None)
        # 未注入 tracer 时退化为 NoopTracer：行为与接入可观测性前完全一致（向后兼容）。
        self._tracer: Tracer = tracer or NoopTracer()
        # 绑定工具 schema：单一真相源 = 各工具的 Pydantic args_schema → OpenAI 格式。
        self.llm = llm.bind_tools(registry.to_openai_schema())
        # 子 Agent 可传入专用 system prompt 覆盖默认；缺省走 build_system_prompt（向后兼容）。
        self.system_prompt = system_prompt or build_system_prompt(registry)

    async def run(
        self,
        user_input: str,
        session_id: Optional[str] = None,
        history: Optional[list[BaseMessage]] = None,
        system_suffix: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """驱动 TAO 循环，流式产出最终回复。

        Args:
            user_input: 本轮用户输入。
            session_id: 会话标识（由调用方按 session 隔离选用对应历史，见 Phase 4）。
            history: 已裁剪的短期记忆窗口（``BaseMessage`` 列表），注入到 system
                prompt 之后、当前 user message 之前；``None`` 时等价于无历史（与
                Phase 3 行为一致）。
            system_suffix: 系统提示补充（如长期偏好提示），追加到 system prompt 末尾；
                ``None``/空串时不追加。

        最终回复（含 ``max_steps`` 兜底）以 ``[REPLY]`` 前缀 yield，调用方可据此
        捕获回复文本并回写会话历史（``AgentLoop`` 自身保持无状态、不写 DB）。
        """
        # ════════════════════════════════════════════════════════════════════
        # ① 组装初始上下文（context engineering 的落点）
        # 顺序固定：系统提示(可带后缀) → 历史 → 本轮用户输入。
        # ════════════════════════════════════════════════════════════════════
        system_content = self.system_prompt
        if system_suffix:
            # system_suffix 典型是「长期偏好提示」（Phase 4 LongTermMemory 生成），
            # 拼到系统提示末尾，让模型这轮带着用户偏好作答。
            system_content = f"{system_content}\n\n{system_suffix}"

        # messages 是贯穿整个循环、喂给 LLM 的对话数组；它会像滚雪球一样越来越长
        # （每轮追加「模型输出」+「工具结果」），直到模型不再要工具、给出最终回复。
        messages: list[BaseMessage] = [SystemMessage(content=system_content)]
        if history:
            # history 由 chat_handler 传入（已按 session 裁好的最近 N 轮）。
            # loop 自身「不持有」任何历史——无状态，故可并发安全复用。
            messages.extend(history)
        messages.append(HumanMessage(content=user_input))  # 末尾放本轮用户消息

        # 打转检测器：跨步累计「连续出现的完全相同工具调用」次数（见 guardrails/budget）。
        spin = SpinDetector(self.repeat_limit)

        # 整次 run 一个 root span；trace_id 由其生成，每步 child span 继承（Phase 6）。
        root = self._tracer.start_span(
            "agent_loop.run",
            attributes={"session_id": session_id} if session_id else None,
        )
        try:
            # ════════════════════════════════════════════════════════════════
            # ② 主循环：用 range 而非 while True——天然带硬上限，绝不会死循环
            # ════════════════════════════════════════════════════════════════
            for _step in range(self.max_steps):
                # 预算护栏：发 LLM 前先估算累计上下文体量，超预算就不再「花钱」调用，
                # 直接优雅收尾（绝不无谓地烧 token）。
                if self.max_tokens is not None and estimate_tokens(messages) > self.max_tokens:
                    yield f"[REPLY]{_FALLBACK_REPLY}"
                    return

                step = self._tracer.start_span("step", parent=root)  # 每轮一个子 span
                try:
                    # ────────────────────────────────────────────────────────
                    # ③ Thought：调 LLM 推理（经超时 + 重试护栏）
                    # ────────────────────────────────────────────────────────
                    # _guarded_invoke 是「只读、幂等」的，可安全重试（见下方方法）。
                    try:
                        ai: AIMessage = await self._guarded_invoke(messages)
                    except GuardrailExhausted:
                        # 重试都失败：不让异常冒泡崩掉请求，记一笔 error 后给兜底回复。
                        self._tracer.add_event(step, "error", {"type": "guardrail_exhausted"})
                        yield f"[REPLY]{_FALLBACK_REPLY}"
                        return
                    messages.append(ai)  # 模型这轮输出也加回上下文（下轮它能看到自己说过啥）
                    self._tracer.add_thought(step, _content_text(ai.content))  # trace：记这步思考
                    self._tracer.set_tokens(step, estimate_tokens(messages))   # trace：记 token 近似

                    # ────────────────────────────────────────────────────────
                    # ④ 分叉点：整个 harness 最重要的 if——决定「继续 or 收工」
                    # ────────────────────────────────────────────────────────
                    tool_calls = ai.tool_calls or []  # 模型这轮想调的工具列表，可能为空
                    if not tool_calls:
                        # 空 = 模型判断信息已够、不再要工具 → 这就是最终回复，结束循环。
                        # 前缀 [REPLY] 是与 chat_handler 的约定，供其择出回复文本回写历史。
                        yield f"[REPLY]{_content_text(ai.content)}"
                        return

                    # 打转检测：连续相同工具调用达上限即终止，是早于 max_steps 的逃生口
                    # （模型陷入「反复调同一工具同一参数」的死胡同时及时止损）。
                    if spin.check(tool_calls):
                        self._tracer.add_event(step, "error", {"type": "spin_detected"})
                        yield f"[REPLY]{_FALLBACK_REPLY}"
                        return

                    # ────────────────────────────────────────────────────────
                    # ⑤ Action + Observation：逐个执行工具，把结果按协议喂回
                    # ────────────────────────────────────────────────────────
                    # 同一轮模型可能要求调多个工具，这里全部执行、全部喂回。
                    for call in tool_calls:
                        self._on_tool_call(call)  # 轻量回调钩子（默认 no-op，可注入做埋点/审计）
                        self._tracer.add_tool_call(
                            step, call.get("name", ""), call.get("args") or {}
                        )
                        # _dispatch「绝不重试」、且吞掉一切异常变成错误字符串（见下方方法）。
                        result = await self._dispatch(call)
                        self._on_observation(call.get("name", ""), result)
                        self._tracer.add_observation(step, call.get("name", ""), result)
                        # 关键：工具结果包成 ToolMessage 加回 messages；tool_call_id 把
                        # 「这条结果」精确对应回「模型的哪次调用」（多调用时不会错位）。
                        messages.append(
                            ToolMessage(content=str(result), tool_call_id=call["id"])
                        )
                    # ☝️ 注意这里没有 return：for 跑完会回到 for _step 顶部进入下一轮，
                    #    带着刚拿到的工具结果再问一次模型——这正是 TAO 的「循环」。
                finally:
                    self._tracer.end_span(step)  # 无论这轮如何结束（return/异常/正常）都关子 span

            # ════════════════════════════════════════════════════════════════
            # ⑥ 兜底：跑满 max_steps 仍没出最终回复 → 安全收尾，绝不无限循环
            # ════════════════════════════════════════════════════════════════
            yield f"[REPLY]{_FALLBACK_REPLY}"
        finally:
            self._tracer.end_span(root)  # 关 root span → 导出整条 trace（中途 return 也会执行）

    async def _guarded_invoke(self, messages: list[BaseMessage]) -> AIMessage:
        """经超时 + 重试护栏发起一次 LLM 调用（只读、幂等，故可安全重试）。

        与 ``_dispatch`` 刻意「不对称」：LLM 调用没有副作用，重发一次顶多多花点钱，
        故遇瞬时故障（超时/连接断）值得重试；重试细节见 ``guardrails/retry``。
        """
        return await guarded_invoke(
            lambda: self.llm.ainvoke(messages),  # 真正发请求的 thunk；每次重试都重新调它
            timeout=self.llm_timeout,            # 单次超时（秒）
            max_attempts=self.llm_max_attempts,  # 最多尝试次数（含首次）
            base_delay=self.llm_base_delay,      # 指数退避基准；0.5→1→2s
            sleep=self._retry_sleep,             # 退避用的 sleep（测试注入 no-op，不真睡）
        )

    async def _dispatch(self, call: dict[str, Any]) -> Any:
        """分发单个工具调用；异常被捕获并作为错误结果回灌（不崩循环）。

        与 ``_guarded_invoke`` 刻意「不对称」：工具可能有副作用（如写库下单），重试
        会重复执行，故这里「绝不重试」、只做错误隔离——把异常吞成一句话当成正常工具
        结果喂回模型，让它下一轮自行补救（换参 / 换工具 / 告知用户）。
        """
        try:
            # call 形如 {"name": 工具名, "args": {...}, "id": 调用id}；分发到 registry。
            return await self.registry.dispatch(call["name"], call.get("args") or {})
        except Exception as exc:  # noqa: BLE001 —— 故意捕获「全部」异常：工具失败须回灌而非冒泡
            return f"工具执行失败（{call.get('name', '?')}）：{exc}"


def _content_text(content: Any) -> str:
    """把 AIMessage.content（可能是 str 或 content blocks 列表）规整为纯文本。

    不同 provider 返回的 content 形态不一：有的是纯字符串，有的是
    ``[{"type": "text", "text": ...}, ...]`` 的 block 列表——这里统一抽成一段文本，
    供 [REPLY] 输出与 token 估算使用。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))  # 只取文本块，忽略图片/工具调用等其它块
        return "".join(parts)
    return str(content)  # 兜底：其它类型直接 str 化
