"""Skill / SkillRegistry 单测（Phase 7：任务 6.3）。

确定性关键词匹配、按需加载、无匹配返回空集、重名报错——全程离线、不触网。
"""

import pytest

from harness.skills.base import Skill
from harness.skills.registry import SkillRegistry


def _rag_skill() -> Skill:
    return Skill(
        name="rag_search",
        description="知识库检索能力",
        content="用知识库检索回答信息类问题。",
        triggers=("价格", "项目", "营业"),
    )


def _pref_skill() -> Skill:
    return Skill(
        name="preference_read",
        description="用户偏好解读能力",
        content="读取并解读用户历史偏好。",
        triggers=("偏好", "推荐"),
    )


def test_load_for_returns_only_matching_skill():
    reg = SkillRegistry()
    reg.register(_rag_skill())
    reg.register(_pref_skill())

    loaded = reg.load_for("帮我查一下这个项目的价格")

    assert [s.name for s in loaded] == ["rag_search"]


def test_load_for_no_match_returns_empty():
    reg = SkillRegistry()
    reg.register(_rag_skill())

    assert reg.load_for("今天天气怎么样") == []


def test_skill_matches_by_name_when_no_triggers():
    skill = Skill(name="upsell", description="加购建议", content="...")
    assert skill.matches("是否需要 upsell 一下") is True
    assert skill.matches("无关内容") is False


def test_duplicate_registration_raises():
    reg = SkillRegistry()
    reg.register(_rag_skill())
    with pytest.raises(ValueError):
        reg.register(_rag_skill())


def test_get_unknown_skill_raises():
    reg = SkillRegistry()
    with pytest.raises(KeyError):
        reg.get("nope")
