"""delegate —— 编排型工具：主 Agent 据此自主派生子 Agent（Phase 7）。

与领域工具不同，``delegate`` 的 handler **不调用 services/**，而是把任务转交给指定的
子 Agent 执行，并把其汇总结果回传给主 Agent。主 Agent（顶层 ``AgentLoop``）通过正常的
tool-calling 路径调用它，由模型自主决定派给哪个子 Agent——取代硬编码路由（黄金准则：
TAO 循环 / 显式优于隐式）。

``build_delegate_tool`` 是工厂：注入 ``llm`` / 全量 ``ToolRegistry`` / ``SubAgentRegistry``，
闭包出一个 ``Tool``。``description`` 在构造时据已注册子 Agent 动态渲染其选项与职责。
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from harness.subagents.registry import SubAgentRegistry
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry


class DelegateArgs(BaseModel):
    """delegate 入参。"""

    subagent: str = Field(description="目标子 Agent 名（必须是可派生选项之一）。")
    task: str = Field(
        description="交给该子 Agent 的完整任务描述，需包含其完成任务所需的上下文。"
    )


def build_delegate_tool(
    llm: BaseChatModel,
    full_registry: ToolRegistry,
    subagent_registry: SubAgentRegistry,
) -> Tool:
    """构造 ``delegate`` 工具。

    Args:
        llm: 子 Agent 运行所用的聊天模型（与主 Agent 共用 provider）。
        full_registry: 全量工具注册中心；子 Agent 据自身 ``tool_names`` 从中切片。
        subagent_registry: 可派生子 Agent 的注册中心。

    Returns:
        一个遵循工具四要素的 ``Tool``，handler 把任务转交对应子 Agent 并回传其结果。
    """
    options = "；".join(
        f"{a.name}（{a.description}）" for a in subagent_registry.all()
    )
    description = (
        "把一个子任务委派给某个专用子 Agent 执行，并返回其结论。"
        "当任务明显属于某个领域时，调用本工具并指定对应子 Agent。"
        f"可派生的子 Agent：{options}。"
        "若任务跨领域，可分多次委派。"
    )

    async def _handler(args: DelegateArgs) -> dict[str, object]:
        if not subagent_registry.has(args.subagent):
            return {
                "success": False,
                "error": (
                    f"未知子 Agent '{args.subagent}'。"
                    f"可选：{subagent_registry.names()}。"
                ),
            }
        agent = subagent_registry.get(args.subagent)
        result = await agent.run(args.task, full_registry, llm)
        return {"success": True, "subagent": args.subagent, "result": result}

    return Tool(
        name="delegate",
        description=description,
        args_schema=DelegateArgs,
        handler=_handler,
    )
