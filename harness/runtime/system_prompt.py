"""harness 系统提示（Phase 3）。

显式声明 agent 的角色、可用工具语义与「何时结束 loop」的指引，取代旧
ClassificationProcessor 里隐式的 if/else 路由约定（黄金准则：显式优于隐式）。

工具的逐条说明书来自各 Tool 的 ``description``（单一真相源），由
``build_system_prompt`` 在运行时拼接，避免在此处重复维护。
"""

from __future__ import annotations

from harness.tools.registry import ToolRegistry

# 角色与行为基线。不在此枚举具体工具——工具清单由 registry 动态注入。
BASE_SYSTEM_PROMPT = (
    "你是一家按摩/推拿门店的智能助手，负责处理来自顾客与工作人员的消息，"
    "覆盖两类事务：服务咨询（价格、项目、技师、营业信息等）与预约办理。\n"
    "\n"
    "工作方式（TAO 循环）：\n"
    "- 你可以调用下面列出的工具来获取信息或执行操作；根据用户意图自主决定调用哪个、"
    "以及是否需要连续多步调用（例如：先查技师，若不可用再查替代技师，最后创建预约）。\n"
    "- 每次工具返回结果后，结合结果判断下一步：还需要更多信息就继续调用工具；"
    "已经能给出完整答复或已完成预约，就直接用自然语言回复用户、不要再做无谓的工具调用。\n"
    "- 与按摩/预约无关的请求（如闲聊、问天气），礼貌说明只能协助按摩与预约相关事务。\n"
    "- 回复用简体中文，语气友好、简洁。"
)


def build_system_prompt(registry: ToolRegistry) -> str:
    """拼接基线提示与当前已注册工具的说明书。"""
    tools = [registry.get(name) for name in registry.names()]
    if not tools:
        return BASE_SYSTEM_PROMPT
    lines = [BASE_SYSTEM_PROMPT, "", "可用工具："]
    for tool in tools:
        lines.append(f"- {tool.name}：{tool.description}")
    return "\n".join(lines)
