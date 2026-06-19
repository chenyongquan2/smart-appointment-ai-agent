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


# frozen=True：实例「不可变」（创建后改字段会报错）。Skill 是只读声明，冻结后可放进
# set / 作 dict key，也避免被误改——契合「薄声明、不持业务状态」的定位。
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

    # ↓ dataclass 字段：声明顺序即构造参数顺序（Skill("name", "desc", "content")）。
    name: str
    description: str
    content: str
    # triggers 用 tuple 而非 list：tuple 不可变，契合 frozen 的「实例只读」语义；
    # default_factory=tuple 给每个实例独立的空元组，避免共享可变默认值的经典坑。
    triggers: tuple[str, ...] = field(default_factory=tuple)

    def matches(self, task: str) -> bool:
        """该 skill 是否与给定任务相关（确定性关键词匹配）。

        刻意「不引向量检索」：纯子串匹配是确定性的——同样输入永远同样结果，故离线、
        无网络也能写断言、可单测（设计要点 D5）。代价是只能精确命中关键词、无语义近似。
        """
        # 没配 triggers 就退化成「拿 name 当唯一触发词」——保证任何 skill 至少能被自己的名字命中。
        keywords = self.triggers or (self.name,)
        # any(...)：任一关键词是 task 的子串即算相关；kw 真值判断顺带滤掉空串触发词。
        return any(kw and kw in task for kw in keywords)
