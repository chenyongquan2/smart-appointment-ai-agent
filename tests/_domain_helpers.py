from domains import build_subagent_registry, build_tool_registry, load_domain


def build_default_registry():
    """测试用：装载缺省域并建 ToolRegistry（原 harness 工厂已随 domain-packages 移除）。"""
    return build_tool_registry(load_domain())


def build_default_subagent_registry():
    """测试用：装载缺省域并建 SubAgentRegistry。"""
    return build_subagent_registry(load_domain())
