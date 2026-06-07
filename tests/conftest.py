"""共享测试夹具。

核心:用确定的假 LLM / 假 embeddings 替换真实模型工厂,使 classification 测试
离线、无需 API key、可复现(见 OpenSpec change: fix-preexisting-test-debt)。

统一缝:
- 各 agent 经 ``config.model_provider.create_chat_model`` 取 LLM —— 在每个导入方
  命名空间 monkeypatch 为返回 ``FakeChatModel``。
- RAG 经 ``services.text_embedding.create_embedding_model`` → ``embed_input`` 取向量
  —— 替换为返回固定向量的假 embeddings(维度与真实索引不符时,KnowledgeService.search
  会 try/except 优雅返回 []，不联网、不崩)。
"""

from typing import Any, List, Optional

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda


_CATEGORIES = {"appointment", "query", "pay", "statistics", "other"}

# 分类用关键词(任务内容里出现即判定),顺序即优先级。
_APPOINTMENT_KW = ("预约", "帮我约", "延长服务", "延长时间")
_QUERY_KW = (
    "价格", "多少钱", "收费", "服务", "项目", "技师", "师傅",
    "好处", "作用", "效果", "按摩", "推拿", "几点", "营业",
    "地址", "在哪", "会员", "优惠",
)


def _classify(task: str) -> str:
    """复刻分类器输出空间的确定性启发式,仅用于测试。"""
    t = (task or "").strip()
    if any(k in t for k in _APPOINTMENT_KW):
        return "appointment"
    if any(k in t for k in _QUERY_KW):
        return "query"
    return "other"


def _join(messages: List[BaseMessage]) -> str:
    parts = []
    for m in messages:
        content = getattr(m, "content", m)
        parts.append(content if isinstance(content, str) else str(content))
    return "\n".join(parts)


def _fake_reply(prompt_text: str) -> str:
    """按 prompt 形态返回确定内容。"""
    # 1. 任务分类(task_classifier):只返回类别英文名
    if "只返回类别英文名" in prompt_text or "归类为以下类别" in prompt_text:
        task = prompt_text.split("任务内容：", 1)[-1] if "任务内容：" in prompt_text else prompt_text
        return _classify(task)
    # 2. 咨询相关性判断(consultation_classifier):返回 YES/NO
    if "YES" in prompt_text and "NO" in prompt_text:
        return "YES"
    # 3. 其它(响应生成 / 输入解析等):返回非空中文,既非错误也非标准拒绝串
    return "您好，关于您的问题我们很乐意为您提供帮助。"


def _prompt_text(value: Any) -> str:
    """把 PromptValue / 消息 / 字符串统一取为纯文本,供启发式判断。"""
    if hasattr(value, "to_string"):
        return value.to_string()
    if hasattr(value, "to_messages"):
        return _join(value.to_messages())
    if isinstance(value, str):
        return value
    return str(value)


def _structured_response(schema: Any, text: str) -> Any:
    """为 with_structured_output 返回确定性的 schema 实例。

    - 含 ``category`` 字段(TaskCategory):按启发式分类;
    - 其它(AppointmentSlots 等):返回 schema 默认值(info_complete=False)。
    """
    fields = getattr(schema, "model_fields", {})
    if "category" in fields:
        task = text.split("任务内容：", 1)[-1] if "任务内容：" in text else text
        return schema(category=_classify(task))
    return schema()


class FakeChatModel(BaseChatModel):
    """离线确定性聊天模型。invoke/ainvoke/stream/astream 均走 _generate。"""

    @property
    def _llm_type(self) -> str:
        return "fake-chat-model"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        content = _fake_reply(_join(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])

    def with_structured_output(self, schema: Any, **kwargs: Any):
        """支持结构化输出:返回一个把 prompt 文本映射为 schema 实例的 Runnable。

        真实模型由 langchain-openai 的 with_structured_output 提供;此处为离线测试
        提供等价能力(见 OpenSpec change: phase-1-structured-output)。
        """
        return RunnableLambda(lambda value: _structured_response(schema, _prompt_text(value)))


class _FakeEmbeddings:
    """返回固定向量的假 embeddings,避免任何网络调用。"""

    def embed_query(self, text: str) -> List[float]:
        return [0.1] * 16

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [[0.1] * 16 for _ in texts]


@pytest.fixture
def fake_llm_env(monkeypatch):
    """把所有真实模型工厂替换为离线假实现。

    在各导入方命名空间打桩(它们用 ``from config.model_provider import ...``,
    源模块打桩不会回灌已导入的名字)。
    """
    def _factory(*args, **kwargs):
        return FakeChatModel()

    for mod in (
        "agents.task_classification_agent",
        "agents.consultant_agent",
        "agents.appointment_agent",
        "agents.user_behavior_agent",
    ):
        monkeypatch.setattr(f"{mod}.create_chat_model", _factory, raising=False)

    monkeypatch.setattr(
        "services.text_embedding.create_embedding_model",
        lambda *a, **k: _FakeEmbeddings(),
        raising=False,
    )
    return FakeChatModel
