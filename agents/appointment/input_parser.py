"""
用户输入解析器

负责解析用户输入并提取预约相关信息。
使用 Pydantic schema + 结构化输出(function calling)约束抽取,
取代裸 JSON + json.loads(见 OpenSpec change: phase-1-structured-output)。
"""

import logging
from typing import Any, Dict, Union

from langchain.prompts import PromptTemplate
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from .schemas import AppointmentSlots

logger = logging.getLogger(__name__)


class InputParser:
    """用户输入解析器"""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self.prompt = self._create_prompt_template()
        # 结构化输出:强制模型返回合法 AppointmentSlots,取代裸 JSON + json.loads。
        self.chain = self.prompt | self.llm.with_structured_output(AppointmentSlots)

    def _create_prompt_template(self) -> PromptTemplate:
        """创建预约信息提取的 Prompt 模板。

        仅保留抽取语义与判断逻辑;不再要求模型自行输出 JSON
        (结构化由 with_structured_output 在协议层保证)。
        """
        from config.time_config import time_config
        current_date = time_config.current_date_str()
        current_datetime = time_config.current_datetime_str()

        return PromptTemplate(
            input_variables=["history", "user_input"],
            template=(
                "你是一个预约机器人,负责帮用户预约服务。请从对话中抽取预约槽位。\n"
                f"当前日期是{current_date},当前北京时间是{current_datetime}。\n"
                "当前已知信息:{history}\n"
                "用户输入:{user_input}\n"
                "抽取与判断逻辑:\n"
                "1. 如用户明确指定了技师姓名(如\"张伟技师\"、\"预约李小美\"),请提取 technician_name。\n"
                "2. 如用户在回应推荐技师的确认问题(如回复\"是\"、\"好\"、\"可以\"、\"不\"、\"不要\"等),"
                "请提取到 confirmation,且不要标记为 unrelated。\n"
                "3. 必需信息判断:指定技师名时需 start_time、project、duration;"
                "未指定技师名时还需 gender。只有所有必需信息都不为\"未知\"时 info_complete 才为 true。\n"
                "4. 如用户问题和预约无关(如问天气、闲聊),unrelated 设为 true;"
                "但对推荐技师的确认回复(是/不等)不应标记为 unrelated。\n"
                "5. start_time 必须换算为标准格式 YYYY-MM-DD HH:MM。"
            ),
        )

    async def extract(
        self, user_input: str, chat_history: InMemoryChatMessageHistory
    ) -> AppointmentSlots:
        """从用户输入中结构化抽取预约槽位。

        会把用户输入与抽取结果写入 chat_history;LLM 调用异常时安全降级为
        info_complete=False 的默认槽位,不抛出异常。
        """
        chat_history.add_message(HumanMessage(content=user_input))

        history_str = "\n".join(
            [
                f"用户:{m.content}" if m.type == "human" else f"机器人:{m.content}"
                for m in chat_history.messages
            ]
        )

        try:
            slots: AppointmentSlots = await self.chain.ainvoke(
                {"history": history_str, "user_input": user_input}
            )
        except Exception:
            logger.error("预约槽位抽取失败", exc_info=True)
            slots = AppointmentSlots()  # 安全降级:info_complete=False

        chat_history.add_message(AIMessage(content=slots.model_dump_json()))
        return slots

    def parse_data(
        self, slots: Union[AppointmentSlots, Dict[str, Any], Any]
    ) -> Dict[str, Any]:
        """将抽取结果转为 dict 视图,兼容调用方的 ``data.get(...)`` 用法。

        - 传入 AppointmentSlots:返回其 model_dump();
        - 传入 dict:原样返回;
        - 其它(含空字符串等无效输入):返回语义安全的默认槽位 dict。
        """
        if isinstance(slots, AppointmentSlots):
            return slots.model_dump()
        if isinstance(slots, dict):
            return slots
        return AppointmentSlots().model_dump()
