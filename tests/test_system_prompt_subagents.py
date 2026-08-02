"""build_system_prompt 列出子 Agent 单测（Phase 7：任务 7.2）。

含 delegate 时主提示列出三个子 Agent 职责；不含 delegate（或不传 subagents）时
与既有行为一致。全程离线。
"""

from domains import load_domain
from harness.runtime.system_prompt import build_system_prompt

_DOMAIN = load_domain()
from tests._domain_helpers import build_default_subagent_registry
from harness.subagents import build_delegate_tool
from harness.tools.registry import ToolRegistry
from tests._domain_helpers import build_default_registry


class _DummyLLM:
    """delegate 工厂只需持有引用，不在本测试中真正调用。"""


def _main_registry_with_delegate(subagents):
    full = build_default_registry()
    delegate = build_delegate_tool(_DummyLLM(), full, subagents)
    main = ToolRegistry()
    main.register(delegate)
    return main


def test_prompt_lists_subagents_when_delegate_present():
    subagents = build_default_subagent_registry()
    main = _main_registry_with_delegate(subagents)

    prompt = build_system_prompt(_DOMAIN.system_prompt, main, subagents)

    assert "可派生的专用子 Agent" in prompt
    for name in ("appointment", "consultant", "user_behavior"):
        assert name in prompt


def test_prompt_unchanged_without_subagents():
    """不传 subagents 时与既有行为一致（仅列工具，无子 Agent 段落）。"""
    full = build_default_registry()
    baseline = build_system_prompt(_DOMAIN.system_prompt, full)

    assert "可派生的专用子 Agent" not in baseline
    assert "可用工具" in baseline


def test_prompt_no_subagent_section_without_delegate():
    """registry 不含 delegate 时，即便传入 subagents 也不渲染子 Agent 段落。"""
    full = build_default_registry()
    subagents = build_default_subagent_registry()

    prompt = build_system_prompt(_DOMAIN.system_prompt, full, subagents)

    assert "可派生的专用子 Agent" not in prompt
