"""真跑生产路径的 AgentLoop 并采集实际工具调用（评估端到端采集）。

为单条用例构造一个**带真 ``Tracer`` 与独立 ``InMemoryExporter`` 沙盒**的主 loop
（主 Agent → ``delegate`` → 子 Agent，与生产路径一致），跑完从该 exporter 的全部 span
还原有序工具序列。与 ``run_evals.py`` 解耦、不复用 ``chat_handler`` 的 NoopTracer 全局
单例，故可用脚本化 fake LLM 离线确定性单测（见 change evals-drive-agentloop-real-tools）。

设计要点：
- **每条用例一个 exporter 沙盒**：互不污染，采集边界清晰（design.md D3）。
- **tracer 透传到子 Agent**：经 ``build_delegate_tool(..., tracer=)`` 让子 Agent 内层
  工具调用可见（否则只看得到主 loop 的 ``delegate``）。
- **采全比松**：返回有序 ``[{name, args}]``（``collect_tool_calls`` 默认剔除编排工具
  ``delegate``）；指标侧只用 name 集合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from evals.trace_collect import collect_tool_calls, collect_tool_outcomes
from harness.observability.exporter import InMemoryExporter
from harness.observability.tracer import Tracer
from harness.runtime import AgentLoop
from harness.runtime.system_prompt import build_system_prompt
from harness.subagents import build_delegate_tool
from harness.subagents.registry import SubAgentRegistry
from harness.tools.registry import ToolRegistry

# 与 AgentLoop 的约定前缀：loop 把「最终回复」以 [REPLY]... 形式 yield 出来。
_REPLY_PREFIX = "[REPLY]"


@dataclass
class CaptureResult:
    """单条用例端到端真跑的采集结果：工具序列 + 工具执行成败 + agent 最终回复文本。"""

    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    reply: str = ""  # agent 最终回复（剥离 [REPLY] 前缀）；judge（改造 4）的输入
    # 工具执行成败序列（change evals-task-success-rate）：[{name, ok}]，与 tool_calls 同源
    # （同一 exporter 沙盒的 observation 事件）、跨所有轮次；供「任务成功率」判终态是否办成。
    tool_outcomes: list[dict[str, Any]] = field(default_factory=list)


def _build_capture_loop(
    llm: BaseChatModel,
    full_registry: ToolRegistry,
    subagents: SubAgentRegistry,
) -> tuple[AgentLoop, InMemoryExporter]:
    """按生产路径拼一个带独立 exporter 沙盒的主 loop（单/多轮共用，避免两份沙盒代码）。

    主 registry 只含 delegate，领域工具藏在子 Agent 子集里；delegate 带上 tracer，
    子 Agent 内层工具调用才会被导出（盲区修复的落点）。返回 loop 与其 exporter 沙盒。
    """
    exporter = InMemoryExporter()
    tracer = Tracer(exporter)
    delegate = build_delegate_tool(llm, full_registry, subagents, tracer=tracer)
    main_registry = ToolRegistry()
    main_registry.register(delegate)
    loop = AgentLoop(
        llm=llm,
        registry=main_registry,
        system_prompt=build_system_prompt(main_registry, subagents),
        tracer=tracer,  # 主 loop 自身的 delegate span 也进沙盒（采集时按默认剔除）
    )
    return loop, exporter


def _extract_reply(token: str, prev: str) -> str:
    """从一个 yield 出的 token 取最终回复：[REPLY] 那条以最后一条为准（与 chat_handler 一致）。"""
    if token.startswith(_REPLY_PREFIX):
        return token[len(_REPLY_PREFIX):]
    return prev


async def run_and_capture(
    user_input: str,
    llm: BaseChatModel,
    full_registry: ToolRegistry,
    subagents: SubAgentRegistry,
) -> CaptureResult:
    """跑一次端到端主 loop，采集实际工具序列**与最终回复文本**（单轮）。

    工具调用正确率（改造 1/2）用 ``tool_calls``；回复质量 judge（改造 4）用 ``reply``。
    单轮在语义上等价于单元素多轮，故直接薄封装 ``run_and_capture_multiturn``（DRY）。

    Args:
        user_input: 单条用例的用户输入。
        llm: 聊天模型（真跑用真 provider；测试可注入脚本化 fake LLM）。
        full_registry: 全量工具注册中心（子 Agent 据 tool_names 切片）。
        subagents: 子 Agent 注册中心。

    Returns:
        ``CaptureResult``：有序工具序列（编排工具 ``delegate`` 默认不计入）+ 最终回复。
    """
    return await run_and_capture_multiturn([user_input], llm, full_registry, subagents)


async def run_and_capture_multiturn(
    turns: list[str],
    llm: BaseChatModel,
    full_registry: ToolRegistry,
    subagents: SubAgentRegistry,
) -> CaptureResult:
    """按轮逐次驱动**同一**主 loop，跨所有轮次采集工具序列与末轮回复（多轮，change evals-multiturn-cases）。

    覆盖单轮评不到的轨迹场景：跨轮维持状态、追问后补全槽位、把多轮信息汇总成一次正确工具链。
    复用单轮的沙盒构造（``_build_capture_loop``）与跨 span 工具还原（``collect_tool_calls``），
    仅在其上加按轮驱动的外层循环。可注入脚本化 fake LLM 离线确定性单测。

    Args:
        turns: 有序的用户话语列表（每个元素是一轮用户输入）。单元素即单轮。
        llm / full_registry / subagents: 同 ``run_and_capture``。

    Returns:
        ``CaptureResult``：**跨所有轮次**按时序还原的有序工具序列 + 工具执行成败 + **末轮**最终回复。
    """
    # ① 单个 exporter 沙盒跨所有轮次：所有轮、所有子 Agent 的 span 进同一沙盒，
    #    collect_tool_calls 据 (span.start, 事件序) 自然跨轮还原全局有序序列。
    loop, exporter = _build_capture_loop(llm, full_registry, subagents)

    # ② 按轮驱动：history 只累积 user/assistant 文本对（与生产 chat_handler 的窗口口径一致，
    #    不回灌轮间中间工具消息——每轮 loop.run 自重建 [System]+history+[Human]）。
    history: list[BaseMessage] = []
    reply = ""
    for turn in turns:
        reply = ""
        # 传入 history 的副本：loop.run 内部会 extend，传副本避免它改到我们累积的列表。
        async for token in loop.run(turn, history=list(history)):
            reply = _extract_reply(token, reply)
        history.append(HumanMessage(content=turn))
        history.append(AIMessage(content=reply))  # 末轮回复即喂 judge 的 reply

    # ③ 跨所有轮次的全部 span 还原有序工具序列 + 工具执行成败（同一沙盒、同排序口径）。
    spans = exporter.spans
    return CaptureResult(
        tool_calls=collect_tool_calls(spans),
        reply=reply,
        tool_outcomes=collect_tool_outcomes(spans),
    )


async def capture_tool_calls(
    user_input: str,
    llm: BaseChatModel,
    full_registry: ToolRegistry,
    subagents: SubAgentRegistry,
) -> list[dict[str, Any]]:
    """薄封装：只取工具序列（向后兼容改造 1 的既有调用点与单测）。"""
    result = await run_and_capture(user_input, llm, full_registry, subagents)
    return result.tool_calls
