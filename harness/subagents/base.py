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

from harness.runtime.agent_loop import AgentLoop
from harness.tools.registry import ToolRegistry

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

    name: str
    description: str
    tool_names: tuple[str, ...]
    system_prompt: str

    async def run(
        self,
        task: str,
        full_registry: ToolRegistry,
        llm: BaseChatModel,
        session_id: Optional[str] = None,
    ) -> str:
        """在独立上下文里跑一次 mini TAO 循环，返回最终文本回复。

        Args:
            task: 主 Agent 交付的任务描述（必要上下文由主 Agent 写入其中）。
            full_registry: 全量工具注册中心；据 ``tool_names`` 切片出本子 Agent 的子集。
            llm: 聊天模型（与主 Agent 共用 provider）。
            session_id: 透传的会话标识（用于 tracer 关联）；不改变隔离语义。

        Returns:
            子 Agent 的最终文本回复（已剥离 ``[REPLY]`` 前缀）。
        """
        subset = full_registry.subset(list(self.tool_names))
        loop = AgentLoop(llm=llm, registry=subset, system_prompt=self.system_prompt)

        reply = ""
        async for token in loop.run(task, session_id=session_id):
            if token.startswith(_REPLY_PREFIX):
                reply = token[len(_REPLY_PREFIX):]
        return reply
