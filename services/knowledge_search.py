"""知识库检索端口——`search_knowledge` 工具与具体检索实现之间的接缝。

本地 RAG（SQLite + FAISS）已于 change ``remove-local-rag`` 移除，知识库将由一个
**独立的 RAG 项目**提供。为了让那次接入不必再动工具层、registry、子 Agent 或评估用例，
这里把「检索」收敛成一个可替换的端口：

- 工具层只依赖 ``KnowledgeSearchPort`` 这个协议（见 ``harness/tools/knowledge.py``）；
- 接入远程 RAG 时，实现一个满足该协议的 client 并 ``set_knowledge_search(client)`` 即可；
- 测试与评估注入返回固定文档的 fake，从而获得**离线确定性**（与 ``tests/conftest.py``
  注入 fake LLM、``test_embedding_timeout.py`` 注入 fake embedding 同构）。

未注入任何实现时的行为见 ``NotConfiguredKnowledgeSearch``——那是本模块最需要读的一段。
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

__all__ = [
    "KnowledgeBackendNotConfigured",
    "KnowledgeSearchPort",
    "NotConfiguredKnowledgeSearch",
    "get_knowledge_search",
    "set_knowledge_search",
]


# 这段文字最终会经 agent loop 的 `_dispatch` 拼进「工具执行失败（search_knowledge）：…」
# 回灌给模型，所以它不只是给人看的日志——后半句是**给模型的行为指令**：明确要求它如实
# 告知而非编造。少了这句，模型很容易拿训练知识现编价格与营业时间。
_NOT_CONFIGURED_MESSAGE = (
    "知识库尚未接入：本地 RAG 已移除，远程 RAG 服务未配置，本次检索没有执行。"
    "请如实告知用户当前无法查询门店知识库，"
    "不要凭猜测回答价格、营业时间、门店政策等需要以知识库为准的信息。"
)


class KnowledgeBackendNotConfigured(RuntimeError):
    """未注入任何知识库检索实现时抛出。

    刻意**抛异常**而非返回空列表或一个「看起来成功」的结构化结果，理由见
    change ``remove-local-rag`` 的 design D2，简述：

    - 返回 ``[]``：模型会读成「查过了、库里没有这条」，进而凭训练知识编造答案；
      且 guardrails 有硬约束「MUST NOT 静默返回空结果而不留痕」。
    - 返回 ``{"available": false, ...}``：模型能读懂，但 ``evals/trace_collect.py``
      判 ``ok`` 只看结果是否以 ``TOOL_FAILURE_PREFIX`` 开头，于是这次调用会被记成
      **执行成功**，`任务成功率` 把「根本没检索到」算作达成业务终态——指标撒谎。

    抛异常则正好走既有的单工具失败回灌路径：``agent_loop._dispatch`` 把它吞成
    ``"工具执行失败（search_knowledge）：…"`` 作为 observation 回灌，**loop 继续**
    （不会崩），同时 ``trace_signals`` 的 ``tool_failure`` 坏信号会点亮，
    ``evals/triage.py`` 的在线闭环能把这些 case 甄别出来——"未接入"这件事在可观测面
    上是看得见的，而不是悄悄把咨询类回答降级。
    """


@runtime_checkable
class KnowledgeSearchPort(Protocol):
    """知识库检索端口。

    入参口径与 ``harness/tools/schemas.py`` 的 ``SearchKnowledgeArgs`` 保持一致，
    使工具层只需「转交」而无需做任何形状转换。

    返回结构化文档列表；每篇文档至少含 ``content``，通常还带 ``category`` / ``score``。
    """

    async def search(
        self,
        query: str,
        top_k: int = 3,
        category: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        ...


class NotConfiguredKnowledgeSearch:
    """缺省实现：任何检索都以「未接入」明确失败收场。"""

    async def search(
        self,
        query: str,
        top_k: int = 3,
        category: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        raise KnowledgeBackendNotConfigured(_NOT_CONFIGURED_MESSAGE)


# 模块级当前实现。默认「未接入」——接入远程 RAG 或在测试/评估里注入 fake 时用
# set_knowledge_search 覆盖。用模块级单值而非依赖注入容器：项目里同类需求
# （fake LLM / fake embedding）一律走 monkeypatch 模块属性，这里保持同一范式。
_current: KnowledgeSearchPort = NotConfiguredKnowledgeSearch()


def get_knowledge_search() -> KnowledgeSearchPort:
    """取当前生效的检索实现。工具 handler 每次调用都经此解析，故注入可即时生效。"""
    return _current


def set_knowledge_search(port: Optional[KnowledgeSearchPort]) -> KnowledgeSearchPort:
    """注入检索实现；传 ``None`` 恢复为「未接入」缺省实现。

    Returns:
        被替换掉的上一个实现——测试可据此在 teardown 里还原，避免用例间串味。
    """
    global _current
    previous = _current
    _current = port if port is not None else NotConfiguredKnowledgeSearch()
    return previous
