"""SubAgent —— 专用子 Agent 抽象（Phase 7）。

一个子 Agent = 一个领域（预约 / 咨询 / 行为分析）的专属「工人」：声明四要素
``name`` / ``description`` / ``tool_names`` / ``system_prompt``，运行时用全量
``ToolRegistry`` 切出自己的工具子集，复用既有 ``AgentLoop`` 在**独立上下文**里跑一次
mini TAO 循环，返回最终文本回复。

设计要点（见 OpenSpec change phase-7-subagents-skills 的 design.md，决策 D1/D2）：
- 复用 ``AgentLoop``（含护栏 / tracer / 错误隔离），不重写循环、不重写业务逻辑。
- 子 Agent 上下文与主 Agent 隔离：仅返回最终汇总文本，中间步骤不外泄。
- 子 Agent 自身无状态——每次 ``run`` 用传入的 ``full_registry`` / ``llm`` 现场构造 loop。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel

from harness.observability.tracer import Tracer
from harness.runtime.agent_loop import AgentLoop
from harness.tools.registry import ToolRegistry

# 与 AgentLoop 的约定前缀：loop 把「最终回复」以 [REPLY]... 形式 yield 出来。
# 子 Agent 只关心最终回复，故据此前缀从 token 流里把它择出来（中间步骤一律丢弃）。
_REPLY_PREFIX = "[REPLY]"


@dataclass(frozen=True)
class SubAgent:
    """一个可被主 Agent 派生的专用子 Agent。

    Attributes:
        name: 唯一子 Agent 名（snake_case），用于注册与 ``delegate`` 派生。
        description: 面向主 Agent 的说明书——它负责哪个领域、何时该派给它。
        tool_names: 该子 Agent 的工具子集（全量 registry 中的工具名）；MUST 非空。
        system_prompt: 该子 Agent 的专用系统提示。
    """

    # 子 Agent 的「四要素」——纯声明式数据，没有任何行为；行为全在下面 run 里复用 AgentLoop。
    # frozen=True（见类装饰器）让实例不可变，故可作为模块级常量安全共享（见 appointment.py 等）。
    name: str
    description: str
    tool_names: tuple[str, ...]  # 用 tuple 而非 list：不可变，契合 frozen dataclass
    system_prompt: str

    async def run(
        self,
        task: str,
        full_registry: ToolRegistry,
        llm: BaseChatModel,
        session_id: Optional[str] = None,
        tracer: Optional[Tracer] = None,
    ) -> str:
        """在独立上下文里跑一次 mini TAO 循环，返回最终文本回复。

        Args:
            task: 主 Agent 交付的任务描述（必要上下文由主 Agent 写入其中）。
            full_registry: 全量工具注册中心；据 ``tool_names`` 切片出本子 Agent 的子集。
            llm: 聊天模型（与主 Agent 共用 provider）。
            session_id: 透传的会话标识（用于 tracer 关联）；不改变隔离语义。
            tracer: 可选 tracer；透传进内层 ``AgentLoop`` 使子 Agent 步内的
                tool_call / observation 被导出（消除子 Agent 工具调用对可观测层的盲区）。
                缺省 ``None`` 时内层 loop 退化 ``NoopTracer``，行为与透传前完全一致。
                内层 loop 仍自开 root span（不嵌套进主 trace 树，见 design.md D2）。

        Returns:
            子 Agent 的最终文本回复（已剥离 ``[REPLY]`` 前缀）。
        """
        # ① 从全量工具里切出「本子 Agent 能用」的子集——这是子 Agent 之间能力隔离的关键：
        #    consultant 拿不到 create_appointment，就不可能误下单（最小权限）。
        subset = full_registry.subset(list(self.tool_names))

        # ② 复用主循环 AgentLoop——不重写 TAO 循环、不重写护栏/tracer/错误隔离。
        #    与主 Agent 的唯一差别只有两处：① 工具子集（subset），② 专用 system_prompt。
        #    每次 run 都现场 new 一个 loop：子 Agent 自身无状态，故天然并发安全。
        #    tracer 透传：注入时子 Agent 工具调用可见；缺省 None 时 AgentLoop 退化 NoopTracer。
        loop = AgentLoop(
            llm=llm, registry=subset, system_prompt=self.system_prompt, tracer=tracer
        )

        # ③ 在「独立上下文」里跑 mini TAO：这里只传 task，不传主 Agent 的 history——
        #    子 Agent 的中间思考/工具调用都困在自己的 messages 里，绝不回流到主 Agent。
        reply = ""
        async for token in loop.run(task, session_id=session_id):
            # loop 会流式 yield 很多 token；我们只在乎以 [REPLY] 开头的那一条（最终回复）。
            # 命中就剥掉前缀、覆盖 reply；循环结束后 reply 即子 Agent 的最终汇总文本。
            if token.startswith(_REPLY_PREFIX):
                reply = token[len(_REPLY_PREFIX):]
        # 只把这段最终文本交还主 Agent——中间步骤不外泄，正是「上下文隔离」的体现。
        return reply
