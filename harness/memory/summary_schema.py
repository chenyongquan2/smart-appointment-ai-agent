"""会话摘要的结构化 schema（add-context-compaction：记忆压缩）。

用 Pydantic 模型约束 LLM 产出的摘要内容，强制保留压缩中最容易丢失、对预约业务
最关键的几类信息（关键实体 / 已做决策 / 未完成事项 / 用户约束），再 ``render()``
为一段提示文本注入上下文。

为何用 structured output 而非自由文本摘要：自由文本压缩极易"顺手"丢掉槽位类关键
信息（如"只要女技师"），而结构化 schema 在协议层强制模型按字段填写，丢失风险显著
降低（与 Phase 1 InputParser 的 with_structured_output 一脉相承）。详见 design.md D3。
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class ConversationSummary(BaseModel):
    """一段会话的结构化摘要。

    每个 Field 的 description 会进入 model_json_schema()，是"写给模型的提示词"，
    直接影响模型怎么归纳。各字段均为字符串列表，便于增量滚动时逐条并入/去重。
    """

    key_entities: List[str] = Field(
        default_factory=list,
        description="对话中出现的关键实体：技师姓名、服务项目、具体日期时间等。",
    )
    decisions: List[str] = Field(
        default_factory=list,
        description="已经做出的决定：如已确认预约某技师某时段、已选定某项目。",
    )
    open_items: List[str] = Field(
        default_factory=list,
        description="尚未完成/待确认的事项：如待用户确认时间、技师不可约需改约等。",
    )
    user_constraints: List[str] = Field(
        default_factory=list,
        description="用户表达的约束与偏好：如只要女技师、只能周末、预算上限、力度偏好等。",
    )

    def render(self) -> str:
        """渲染为注入上下文的提示文本；全部为空时返回空串。

        以小标题分段，让模型一眼分清"已定/未定/约束"，尤其确保 user_constraints
        与 open_items 醒目，避免后续轮次违背早期约束。
        """
        sections = [
            ("用户约束/偏好", self.user_constraints),
            ("已做决定", self.decisions),
            ("待办/未确认", self.open_items),
            ("关键实体", self.key_entities),
        ]
        lines: List[str] = []
        for title, items in sections:
            if items:
                lines.append(f"【{title}】")
                lines.extend(f"- {item}" for item in items)
        if not lines:
            return ""
        return "以下是更早对话的摘要（窗口外较旧回合，已压缩）：\n" + "\n".join(lines)
