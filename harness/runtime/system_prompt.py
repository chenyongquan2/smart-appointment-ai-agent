"""harness 系统提示（Phase 3）。

显式声明 agent 的角色、可用工具语义与「何时结束 loop」的指引，取代旧
ClassificationProcessor 里隐式的 if/else 路由约定（黄金准则：显式优于隐式）。

工具的逐条说明书来自各 Tool 的 ``description``（单一真相源），由
``build_system_prompt`` 在运行时拼接，避免在此处重复维护。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from harness.tools.registry import ToolRegistry

if TYPE_CHECKING:  # 仅类型注解，运行时不 import，避免与 subagents→runtime 形成循环。
    from harness.subagents.registry import SubAgentRegistry

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


def build_system_prompt(
    registry: ToolRegistry,
    subagents: Optional["SubAgentRegistry"] = None,
) -> str:
    """拼接基线提示与当前已注册工具的说明书。

    当主 registry 含 ``delegate`` 工具且传入 ``subagents`` 时，额外把可派生子 Agent 的
    职责清单渲染进提示（显式优于隐式），使主 Agent 知道「有哪些专员、各管什么」。
    不含 ``delegate`` 或未传 ``subagents`` 时，行为与既有完全一致（向后兼容）。
    """
    # ──────────────────────────────────────────────────────────────────────
    # 本函数产出的系统提示分三块，「必要性」截然不同（理解这点很关键）：
    #   A. BASE_SYSTEM_PROMPT（角色 + TAO + 何时停 + 边界）—— 必需、不可替代。
    #      这些「跨工具的策略与边界」无法由工具 schema 表达，删了模型会乱答/跑题/该停不停。
    #   B. 下面「可用工具：」逐条回显 —— 对「模型能不能调用工具」而言【基本冗余】。
    #      模型能调工具，靠的是 bind_tools 注入的 API ``tools`` 字段（即
    #      registry.to_openai_schema() 的产物，见 agent_loop.py 绑定处），不是这段文字。
    #      删掉这段，模型照样能调；保留它只是「动态生成、零维护、人类可读」的低成本取舍。
    #   C. 子 Agent 清单 —— 「回显」里最值得保留的一项。子 Agent 不是一等公民工具
    #      （不进 ``tools`` 字段），把「有哪些专员、各管什么」明写出来，对主 Agent 选对
    #      delegate 的 subagent 参数确有帮助（虽然 delegate.description 内也嵌了一份）。
    # ⚠️ 耦合点：BASE 里「你可以调用下面列出的工具」一句引用了 B；若要精简删 B，
    #    需顺手改这句措辞，否则会出现「说有清单、下面却没有」。
    # ──────────────────────────────────────────────────────────────────────

    # ① 从注册中心动态取出当前所有工具对象（顺序由 registry.names() 决定）。
    #    「动态注入」的意义：工具清单是运行时拼出来的，不是写死在提示里——
    #    新增/删除一个工具，这段提示会自动跟着变，无需手改文案（单一真相源）。
    tools = [registry.get(name) for name in registry.names()]
    if not tools:
        return BASE_SYSTEM_PROMPT  # 一个工具都没注册：只回基线提示，不拼空的「可用工具：」段
    # lines 是「一行一条」地攒提示内容，最后用换行拼成整段；空串 "" 用来制造空行分隔。
    # 注：lines[0] 即上文说的【A】（必需）；下面这段「可用工具：」即【B】（对机制基本冗余）。
    lines = [BASE_SYSTEM_PROMPT, "", "可用工具："]
    for tool in tools:
        # 每个工具的说明书 = 它自己的 description（单一真相源）。
        # 易误解点：这里不重复描述工具用法，全靠各 Tool 类里写好的 description——
        # 想改某工具的说明，去改那个工具，而不是改这里。
        lines.append(f"- {tool.name}：{tool.description}")

    # ② 子 Agent 清单（即上文的【C】，「回显」里最值得保留的一项）（Phase 7）：
    #    仅当「主 registry 里有 delegate 工具」且「传了 subagents」时才渲染。
    #    两个条件缺一不可——没有 delegate 工具，模型也无从委派，列清单只会徒增干扰。
    if subagents is not None and "delegate" in registry.names():
        members = subagents.all()
        if members:
            # 把「有哪些专员、各管什么」明明白白写进提示（显式优于隐式），
            # 让主 Agent 知道何时该用 delegate 把活派给哪个子 Agent。
            lines.extend(["", "可派生的专用子 Agent（用 delegate 工具委派）："])
            for agent in members:
                lines.append(f"- {agent.name}：{agent.description}")
    return "\n".join(lines)  # 各行用换行拼接，得到最终系统提示字符串
