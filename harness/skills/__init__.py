"""harness Skills 层（Phase 7：子 Agent / Skills 化）。

把可复用能力声明为带描述的 ``Skill``，由 ``SkillRegistry`` 按任务描述**按需加载**
（而非全量常驻），对齐 Claude Code skills 机制。
"""

from harness.skills.base import Skill
from harness.skills.registry import SkillRegistry

__all__ = ["Skill", "SkillRegistry"]
