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
        # 以 skill.name 为键的字典：天然保证名字唯一，按名 get/查重都是 O(1)。
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """注册 skill；name 已存在则报错，拒绝覆盖。"""
        # 重名即报错（fail-fast）而非静默覆盖：与其它注册中心口径一致，防「同名 skill
        # 悄悄顶掉」这类难查的配置错误尽早暴露。
        if skill.name in self._skills:
            raise ValueError(f"Skill '{skill.name}' 已注册，拒绝覆盖。")
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        """按名取 skill；不存在则报错。"""
        # 缺失即抛 KeyError 而非返回 None：调用方拿到的永远是有效 Skill，不必到处判空。
        if name not in self._skills:
            raise KeyError(f"未注册的 skill：'{name}'。")
        return self._skills[name]

    def names(self) -> list[str]:
        # list(dict) 取的是「键」（即所有 skill 名）；插入序在 py3.7+ 字典里是稳定的。
        return list(self._skills)

    def load_for(self, task: str) -> list[Skill]:
        """按任务描述匹配并返回相关 skill；无匹配返回空集（不报错）。

        这就是「按需加载」的落点：只挑与本次任务相关的 skill 注入，而非把全部 skill
        常驻上下文——省 token、也少干扰模型。无匹配返回 [] 而非报错，调用方可放心
        ``for s in load_for(...)`` 直接迭代（空集就是不注入任何 skill）。
        """
        # 逐个问每个 skill「你和这个任务相关吗」（Skill.matches 的确定性关键词匹配）。
        return [skill for skill in self._skills.values() if skill.matches(task)]
