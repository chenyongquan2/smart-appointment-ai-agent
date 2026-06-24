"""LLM-as-judge：对 agent 最终回复做回复质量裁决（改造 4）。

judge 是评估里唯一「主观维度」的判法——回复是否恰当、正确、有帮助无法用 ``==``/``set``
客观判定（教材 §6）。本模块是 judge 的**调用层**：触网、非确定，但 ``llm`` 可注入，故可用
脚本化 fake judge 离线确定性单测（复刻改造 1「采集层触网 / metrics 纯函数」的分层）。

设计要点（见 change evals-llm-judge-response-quality 的 design.md）：
- **结构化裁决**：``with_structured_output(JudgeVerdict)`` 在协议层强制返回合法 JSON，
  不解析自由文本（黄金准则：结构化输出 > 字符串解析）。
- **reason 先于 passed**：字段顺序让模型先写理由再下结论，减少「拍脑袋」裁决。
- **二元 pass/fail**：最稳、最易聚合（通过率）、最易与人工算 Cohen's κ 校准（见 metrics）。
- judge 的**自我偏好**（与 agent 同模型）、长度偏差等是已知局限，rubric 尽量压、不保证根除；
  judge 在与人工校准前 MUST 被报告标为「未校准」（见 run_evals / metrics）。
"""

from __future__ import annotations

import logging

from langchain.prompts import PromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class JudgeVerdict(BaseModel):
    """裁判对单条回复的二元质量裁决。

    字段顺序刻意「reason 在前、passed 在后」：引导模型先推理后裁决（结构化输出按字段
    顺序生成），减少不假思索的判定。
    """

    reason: str = Field(description="判定理由：先分析回复是否恰当/正确/有帮助，再给结论。")
    passed: bool = Field(description="该回复是否恰当且正确地回应了用户请求（True=合格）。")


# rubric 只描述「什么算合格」，不规定输出格式（结构化由 with_structured_output 在协议层保证）。
# 明确「按内容判，不因长度/措辞礼貌加分」——压长度偏差（压不净者列为已知局限）。
_JUDGE_TEMPLATE = (
    "你是一个服务预约助手的质量裁判。给定用户输入与助手的回复，判断这条回复是否"
    "**恰当且正确地回应了用户请求**。\n"
    "合格(passed=True)的标准（复合判断）：\n"
    "- 相关：回应了用户实际问的/要的，没有答非所问；\n"
    "- 正确：没有明显事实错误或与上下文矛盾；\n"
    "- 有帮助：推进了任务（给出信息、可执行的下一步，或在信息不足时进行了恰当的追问）。\n"
    "判定原则：只看**内容**是否合格，不因回复更长或措辞更客气而加分。\n"
    "请先在 reason 里简要分析，再给出 passed。\n\n"
    "用户输入：{user_input}\n"
    "助手回复：{reply}"
)


def build_judge_chain(llm: BaseChatModel):
    """构造 judge 链：``prompt | llm.with_structured_output(JudgeVerdict)``。

    llm 由调用方注入（真跑用 temperature=0 的真 provider；测试注入脚本化 fake judge）。
    """
    prompt = PromptTemplate(input_variables=["user_input", "reply"], template=_JUDGE_TEMPLATE)
    return prompt | llm.with_structured_output(JudgeVerdict)


async def judge_response(user_input: str, reply: str, llm: BaseChatModel) -> JudgeVerdict:
    """对单条回复做质量裁决，返回 ``JudgeVerdict``。

    Args:
        user_input: 用户输入。
        reply: agent 的最终回复文本（由 ``agent_capture.run_and_capture`` surface）。
        llm: 裁判模型（可注入）。

    Returns:
        ``JudgeVerdict``；调用异常时安全降级为 ``passed=False`` 并在 reason 标注异常
        （不让 judge 故障拖垮整轮评估；该条会被如实计为不通过）。
    """
    try:
        chain = build_judge_chain(llm)
        return await chain.ainvoke({"user_input": user_input, "reply": reply})
    except Exception as exc:  # noqa: BLE001 —— judge 故障不崩整轮；如实记不通过
        logger.error("judge 调用失败", exc_info=True)
        return JudgeVerdict(reason=f"<judge 异常:{type(exc).__name__}>", passed=False)
