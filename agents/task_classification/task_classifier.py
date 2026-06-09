"""
任务分类器 - 专门负责判断用户请求的类型

职责：
1. 接收用户输入，分析其意图
2. 根据预定义的分类规则，将任务归类为：
   - appointment（预约任务）
   - query（查询任务）  
   - pay（支付任务）
   - statistics（统计任务）
   - other（其他任务）
3. 提供清晰的分类结果和置信度
"""

import logging
from langchain.prompts import PromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel

from .schemas import TaskCategory

logger = logging.getLogger(__name__)


class TaskClassifier:
    """任务分类器 - 使用LLM进行智能任务分类"""

    def __init__(self, llm: BaseChatModel):
        self.llm = llm
        self._initialize_prompt()
        # 结构化输出:用 function calling 强制模型返回合法枚举,
        # 取代 strip().lower() + 白名单兜底(黄金准则:结构化输出 > 字符串解析)。
        self.chain = self.prompt | self.llm.with_structured_output(TaskCategory)
    
    def _initialize_prompt(self):
        """初始化分类提示词模板。

        只描述分类语义,不规定输出格式(结构化由 with_structured_output 在协议层保证)。
        """
        self.prompt = PromptTemplate(
            input_variables=["task"],
            template=(
                "你是一个服务预约系统的助手，你会处理来自用户和工作人员的消息，请判断本次任务的意图类别。\n"
                "分类口径：\n"
                "- 用户咨询服务价格、有哪些工作人员、各自特点、地址营业等 → 查询任务(query)。\n"
                "- 用户请求预约(如'请帮我预约今天下午3点的服务1小时')，"
                "或工作人员告知某用户需延长服务时间 → 预约任务(appointment)。\n"
                "- appointment 机器人告知用户已选定某位工作人员做某个项目 → 支付任务(pay)。\n"
                "- 工作人员上报已完成当前任务 → 统计任务(statistics)。\n"
                "- 与上述都无关(如闲聊、问天气) → 其它任务(other)。\n"
                "以下是本次归类任务:\n"
                "任务内容：{task}"
            )
        )
    
    async def classify_task(self, task: str) -> str:
        """
        分类任务
        
        Args:
            task: 用户输入的任务内容
            
        Returns:
            str: 分类结果 ('appointment', 'query', 'pay', 'statistics', 'other')
        """
        try:
            result: TaskCategory = await self.chain.ainvoke({"task": task})
            return result.category

        except Exception:
            logger.error("任务分类失败", exc_info=True)
            return 'other'  # LLM 调用异常时安全降级为其他
    
    def get_category_description(self, category: str) -> str:
        """获取分类类别的描述信息"""
        descriptions = {
            'appointment': '预约任务 - 用户或工作人员的预约相关请求',
            'query': '查询任务 - 用户咨询服务信息、价格、工作人员等',
            'pay': '支付任务 - 完成预约后的支付相关事务',
            'statistics': '统计任务 - 工作人员上报工作完成状态',
            'other': '其他任务 - 与按摩服务无关的请求'
        }
        return descriptions.get(category, '未知任务类型')
