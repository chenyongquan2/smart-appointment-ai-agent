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
        on_tool_call / on_observation: 可选 trace 钩子（默认 no-op，Phase 6 接入）。
    """

    def __init__(
        self,
        llm: BaseChatModel,
        registry: ToolRegistry,
        max_steps: int = 8,
        on_tool_call: Optional[Callable[[dict[str, Any]], None]] = None,
        on_observation: Optional[Callable[[str, Any], None]] = None,
    ) -> None:
        self.registry = registry
        self.max_steps = max_steps
        self._on_tool_call = on_tool_call or (lambda call: None)
        self._on_observation = on_observation or (lambda name, result: None)
        # 绑定工具 schema：单一真相源 = 各工具的 Pydantic args_schema → OpenAI 格式。
        self.llm = llm.bind_tools(registry.to_openai_schema())
        self.system_prompt = build_system_prompt(registry)

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
        system_content = self.system_prompt
        if system_suffix:
            system_content = f"{system_content}\n\n{system_suffix}"

        messages: list[BaseMessage] = [SystemMessage(content=system_content)]
        if history:
            messages.extend(history)
        messages.append(HumanMessage(content=user_input))

        for _step in range(self.max_steps):
            ai: AIMessage = await self.llm.ainvoke(messages)
            messages.append(ai)

            tool_calls = ai.tool_calls or []
            if not tool_calls:
                # 模型给出最终回复 —— 结束循环。
                yield f"[REPLY]{_content_text(ai.content)}"
                return

            # 有工具调用：逐个执行并把结果按协议喂回（同一步的多个调用全部喂回）。
            for call in tool_calls:
                self._on_tool_call(call)
                result = await self._dispatch(call)
                self._on_observation(call.get("name", ""), result)
                messages.append(
                    ToolMessage(content=str(result), tool_call_id=call["id"])
                )

        # 触达 max_steps 仍未得到最终回复：安全兜底，绝不无限循环。
        yield f"[REPLY]{_FALLBACK_REPLY}"

    async def _dispatch(self, call: dict[str, Any]) -> Any:
        """分发单个工具调用；异常被捕获并作为错误结果回灌（不崩循环）。"""
        try:
            return await self.registry.dispatch(call["name"], call.get("args") or {})
        except Exception as exc:  # noqa: BLE001 —— 工具失败须回灌而非冒泡
            return f"工具执行失败（{call.get('name', '?')}）：{exc}"


def _content_text(content: Any) -> str:
    """把 AIMessage.content（可能是 str 或 content blocks 列表）规整为文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
        return "".join(parts)
    return str(content)
