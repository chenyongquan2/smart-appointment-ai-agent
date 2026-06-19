"""摘要记忆层接口与占位实现（Phase 4：状态与记忆 —— 留 stub）。

约定：当会话历史超过短期窗口阈值（``len(history) > window_turns``）时，本应把
窗口外的较旧回合压缩为一段摘要文本，以在不超出上下文预算的前提下保留早期信息。

本 Phase **只定义接口 + 占位实现**（不做真正压缩）：窗口外的旧回合不注入 LLM
上下文（由 ``ShortTermMemory`` 的窗口裁剪负责），但仍持久化在 DB。真正的压缩逻辑
（调用 LLM 生成摘要、缓存摘要）留待后续 Phase。

详见 OpenSpec change phase-4-state-memory design.md D5。
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from harness.runtime.session import Turn


@runtime_checkable
class SummaryMemory(Protocol):
    """摘要记忆契约。

    ``summarize`` 输入窗口外的较旧回合，返回一段摘要文本（供注入上下文）。
    """

    def summarize(self, old_turns: Sequence[Turn]) -> str:
        # 这是「契约」而非实现：Protocol 只规定方法签名（输入窗外旧轮、输出一段摘要文本），
        # 任何长这样的类都自动算作 SummaryMemory（结构化鸭子类型），无需显式继承。
        # 函数体 `...` 是占位，Protocol 不需要真正实现。
        ...


class NoOpSummary:
    """占位实现：不做任何压缩，始终返回空摘要。

    触发条件（约定）：``len(history) > window_turns`` 时本应调用 ``summarize``；
    本占位实现直接返回空串——窗口外旧回合不会以摘要形式注入上下文（它们仍被
    持久化保留）。整体对话流程不受影响、不抛异常。
    """

    def summarize(self, old_turns: Sequence[Turn]) -> str:  # noqa: D401
        # 设计意图：本 Phase 故意「先搭骨架、不上真功能」。返回空串 = 不产出任何摘要，
        # 于是窗外旧轮既不被压缩、也不注入上下文（裁掉它们的是 ShortTermMemory 的窗口）。
        # 这样做的好处：接口已定下、调用点已接通，后续真正实现压缩时只需替换本类，
        # 上层（loop/handler）一行都不用改。返回空串而非抛异常，保证现在流程也能正常跑通。
        return ""
