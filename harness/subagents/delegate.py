"""delegate —— 编排型工具：主 Agent 据此自主派生子 Agent（Phase 7）。

与领域工具不同，``delegate`` 的 handler **不调用 services/**，而是把任务转交给指定的
子 Agent 执行，并把其汇总结果回传给主 Agent。主 Agent（顶层 ``AgentLoop``）通过正常的
tool-calling 路径调用它，由模型自主决定派给哪个子 Agent——取代硬编码路由（黄金准则：
TAO 循环 / 显式优于隐式）。

``build_delegate_tool`` 是工厂：注入 ``llm`` / 全量 ``ToolRegistry`` / ``SubAgentRegistry``，
闭包出一个 ``Tool``。``description`` 在构造时据已注册子 Agent 动态渲染其选项与职责。
"""

from __future__ import annotations

from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from harness.observability.tracer import Tracer
from harness.subagents.registry import SubAgentRegistry
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry


class DelegateArgs(BaseModel):
    """delegate 入参。"""

    # 这两个 Field 的 description 不是给人看的注释——它们会进入 OpenAI tool schema，
    # 直接喂给主 Agent 的 LLM，是模型「学会怎么填参数」的唯一依据（结构化输出 > 字符串解析）。
    subagent: str = Field(description="目标子 Agent 名（必须是可派生选项之一）。")
    task: str = Field(
        description="交给该子 Agent 的完整任务描述，需包含其完成任务所需的上下文。"
    )


def build_delegate_tool(
    llm: BaseChatModel,
    full_registry: ToolRegistry,
    subagent_registry: SubAgentRegistry,
    tracer: Optional[Tracer] = None,
) -> Tool:
    """构造 ``delegate`` 工具。

    Args:
        llm: 子 Agent 运行所用的聊天模型（与主 Agent 共用 provider）。
        full_registry: 全量工具注册中心；子 Agent 据自身 ``tool_names`` 从中切片。
        subagent_registry: 可派生子 Agent 的注册中心。
        tracer: 可选 tracer；透传给被派生子 Agent 的 ``run``，使其内层工具调用被导出
            （消除子 Agent 工具调用的可观测盲区）。缺省 ``None`` 时子 Agent 退化
            ``NoopTracer``，行为与透传前完全一致。

    Returns:
        一个遵循工具四要素的 ``Tool``，handler 把任务转交对应子 Agent 并回传其结果。
    """
    # ① 在「构造时」把当前所有子 Agent 的 name+description 拼成可选项清单。
    #    动态渲染而非写死：日后新增子 Agent，delegate 的说明书会自动更新，无需改这里。
    options = "；".join(
        f"{a.name}（{a.description}）" for a in subagent_registry.all()
    )
    # ② description 是给主 Agent 的 LLM 看的「工具说明书」——它据此判断「何时该委派、派给谁」。
    #    这就是用 tool-calling 取代硬编码 if/else 路由的根：路由决策交还模型，而非写死在代码里。
    description = (
        "把一个子任务委派给某个专用子 Agent 执行，并返回其结论。"
        "当任务明显属于某个领域时，调用本工具并指定对应子 Agent。"
        f"可派生的子 Agent：{options}。"
        "若任务跨领域，可分多次委派。"
    )

    # ③ handler 是闭包：捕获了上面注入的 llm / full_registry / subagent_registry。
    #    注意它与领域工具的本质区别——不碰 services/，而是把任务「再转包」给子 Agent。
    async def _handler(args: DelegateArgs) -> dict[str, object]:
        # 防御：模型可能填了不存在的子 Agent 名。不抛异常，而是回一段错误结果——
        #    让主循环把它当普通工具结果喂回模型，由模型下一轮自行改派（错误隔离，见 AgentLoop._dispatch）。
        if not subagent_registry.has(args.subagent):
            return {
                "success": False,
                "error": (
                    f"未知子 Agent '{args.subagent}'。"
                    f"可选：{subagent_registry.names()}。"
                ),
            }
        # 取出目标子 Agent，在其独立上下文里跑一遍 mini TAO；result 是已剥 [REPLY] 的最终文本。
        # tracer 透传：注入时子 Agent 内层工具调用会被导出（盲区修复）；缺省 None 行为不变。
        agent = subagent_registry.get(args.subagent)
        result = await agent.run(args.task, full_registry, llm, tracer=tracer)
        # 结构化返回（success/subagent/result）——主 Agent 拿到的是「子 Agent 的结论」这一条干净结果。
        return {"success": True, "subagent": args.subagent, "result": result}

    # ④ 最终产出一个再普通不过的 Tool（四要素：name/description/args_schema/handler）。
    #    关键认知：delegate 从主 Agent 视角看，和 find_technician 这类领域工具毫无二致——
    #    它走的是完全相同的 tool-calling 路径，「派生子 Agent」只是它 handler 内部的事。
    return Tool(
        name="delegate",
        description=description,
        args_schema=DelegateArgs,
        handler=_handler,
    )
