"""Skill —— 可复用能力的薄声明（Phase 7）。

一个 Skill = 一段「按需加载」的能力声明：``name`` / ``description``（用于加载决策——
说明它提供什么、何时该加载）/ ``content``（被判定相关时注入子 Agent 上下文的内容，如
补充提示片段）。可选 ``triggers`` 提供确定性匹配关键词。

设计要点（见 OpenSpec change phase-7-subagents-skills 的 design.md，决策 D5）：
- 对齐 Claude Code skills「按需加载、不常驻」理念。
- 匹配走确定性规则（关键词），不引入向量检索，保证离线可测。
- Skill 是薄声明，不重写业务逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Skill:
    """一个可按需加载的可复用能力。

    Attributes:
        name: 唯一 skill 名（snake_case）。
        description: 面向加载决策的说明——它提供什么能力、何时该加载。
        content: 被加载时注入上下文的内容（如补充提示片段）。
        triggers: 触发加载的关键词；任一出现在任务文本中即判定相关。
            为空时退化为「用 ``name`` 作为唯一触发词」。
    """

    name: str
    description: str
    content: str
    triggers: tuple[str, ...] = field(default_factory=tuple)

    def matches(self, task: str) -> bool:
        """该 skill 是否与给定任务相关（确定性关键词匹配）。"""
        keywords = self.triggers or (self.name,)
        return any(kw and kw in task for kw in keywords)
