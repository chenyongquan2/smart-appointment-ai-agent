"""SkillRegistry —— 按需加载可复用能力（Phase 7）。

注册 skill、按名查找、并按任务描述匹配**按需加载**相关 skill（而非全量常驻）。
加载是确定性、可断言的：``load_for(task)`` 返回所有与任务相关的 skill；无匹配返回空集
（不报错）。重名注册报错（与其它注册中心一致）。
"""

from __future__ import annotations

from harness.skills.base import Skill


class SkillRegistry:
    """Skill 注册中心。"""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """注册 skill；name 已存在则报错，拒绝覆盖。"""
        if skill.name in self._skills:
            raise ValueError(f"Skill '{skill.name}' 已注册，拒绝覆盖。")
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        """按名取 skill；不存在则报错。"""
        if name not in self._skills:
            raise KeyError(f"未注册的 skill：'{name}'。")
        return self._skills[name]

    def names(self) -> list[str]:
        return list(self._skills)

    def load_for(self, task: str) -> list[Skill]:
        """按任务描述匹配并返回相关 skill；无匹配返回空集（不报错）。"""
        return [skill for skill in self._skills.values() if skill.matches(task)]
