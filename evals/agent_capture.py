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

from evals.trace_collect import collect_tool_calls
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
    """单条用例端到端真跑的采集结果：工具序列 + agent 最终回复文本。"""

    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    reply: str = ""  # agent 最终回复（剥离 [REPLY] 前缀）；judge（改造 4）的输入


async def run_and_capture(
    user_input: str,
    llm: BaseChatModel,
    full_registry: ToolRegistry,
    subagents: SubAgentRegistry,
) -> CaptureResult:
    """跑一次端到端主 loop，采集实际工具序列**与最终回复文本**。

    工具调用正确率（改造 1/2）用 ``tool_calls``；回复质量 judge（改造 4）用 ``reply``。

    Args:
        user_input: 单条用例的用户输入。
        llm: 聊天模型（真跑用真 provider；测试可注入脚本化 fake LLM）。
        full_registry: 全量工具注册中心（子 Agent 据 tool_names 切片）。
        subagents: 子 Agent 注册中心。

    Returns:
        ``CaptureResult``：有序工具序列（编排工具 ``delegate`` 默认不计入）+ 最终回复。
    """
    # ① 每条用例一个独立 exporter 沙盒 + tracer：采集边界清晰、用例间互不污染。
    exporter = InMemoryExporter()
    tracer = Tracer(exporter)

    # ② 按生产路径拼主 loop：主 registry 只含 delegate，领域工具藏在子 Agent 子集里。
    #    关键：delegate 带上 tracer，子 Agent 内层工具调用才会被导出（盲区修复的落点）。
    delegate = build_delegate_tool(llm, full_registry, subagents, tracer=tracer)
    main_registry = ToolRegistry()
    main_registry.register(delegate)
    loop = AgentLoop(
        llm=llm,
        registry=main_registry,
        system_prompt=build_system_prompt(main_registry, subagents),
        tracer=tracer,  # 主 loop 自身的 delegate span 也进沙盒（采集时按默认剔除）
    )

    # ③ 驱动循环：截留最终回复（[REPLY] 那条），其余 token 仅触发 tracer 副作用。
    reply = ""
    async for token in loop.run(user_input):
        if token.startswith(_REPLY_PREFIX):
            reply = token[len(_REPLY_PREFIX):]  # 多次 [REPLY] 以最后一条为准（与 chat_handler 一致）

    # ④ 从沙盒里所有 span 还原有序工具序列（不按单一 trace_id 过滤——子 Agent 自开 root）。
    return CaptureResult(tool_calls=collect_tool_calls(exporter.spans), reply=reply)


async def capture_tool_calls(
    user_input: str,
    llm: BaseChatModel,
    full_registry: ToolRegistry,
    subagents: SubAgentRegistry,
) -> list[dict[str, Any]]:
    """薄封装：只取工具序列（向后兼容改造 1 的既有调用点与单测）。"""
    result = await run_and_capture(user_input, llm, full_registry, subagents)
    return result.tool_calls
