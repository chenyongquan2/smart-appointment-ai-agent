"""Web HTTP 端点的端到端回归测试（change: feishu-channel-integration，tasks 2.2）。

**这是「Web 改道 executor 后对外行为不变」的唯一有效证据。**

为什么不能用 `evals/` 顶替：`evals/agent_capture.py` 直接构造 `AgentLoop`，完全不经过
`api/chat_handler`、`web/routes` 与 `executor`——它对本次改动不敏感，改道前后的数字必然
一致。拿那个"没变化"当无回归结论是假阳性（详见 change 的 design.md「验证覆盖边界」）。

打的是真实 FastAPI 路由（`starlette.TestClient`），LLM 与持久层注入离线 fake，
不触网、不写真实 DB。
"""

from __future__ import annotations

from typing import Any, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import api.chat_handler as ch
from harness.runtime import AgentLoop
from harness.runtime.session import SessionStore
from harness.memory.long_term import LongTermMemory
from harness.tools.registry import ToolRegistry
from web.routes import router as web_router


class CapturingModel(BaseChatModel):
    """记录每次 invoke 收到的 messages，固定回复一句话。"""

    reply: str = "好的。"
    last_messages: List[BaseMessage] = []

    @property
    def _llm_type(self) -> str:
        return "capturing"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "CapturingModel":
        return self

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        object.__setattr__(self, "last_messages", list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.reply))])


class _NoopSummaryMemory:
    """离线占位摘要记忆（与 test_chat_handler_e2e 同款）：读侧走兜底、写侧 no-op。"""

    def get_read_context(self, session_id: str):
        raise NotImplementedError("offline noop: force fallback to short-term path")

    def get_summary_hint(self, session_id: str) -> str:
        return ""

    async def compact_if_needed(self, session_id: str) -> None:
        return None


@pytest.fixture
def client(monkeypatch):
    """挂载真实 web 路由，但把 chat_handler 的模块级单例换成离线 fake。"""
    llm = CapturingModel()
    monkeypatch.setattr(ch, "_agent_loop", AgentLoop(llm=llm, registry=ToolRegistry()))
    monkeypatch.setattr(ch, "_session_store", SessionStore(repo=None))
    monkeypatch.setattr(ch, "_long_term", LongTermMemory(None))
    monkeypatch.setattr(ch, "_summary", _NoopSummaryMemory())

    app = FastAPI()
    app.include_router(web_router)
    with TestClient(app) as c:
        c.llm = llm  # 供断言取回上下文
        yield c


def post_chat(client: TestClient, message: str, session_id: str | None = None):
    payload: dict[str, Any] = {"message": message}
    if session_id is not None:
        payload["session_id"] = session_id
    return client.post("/chat/stream", json=payload)


# --------------------------------------------------------------------------- #
# ① token 序列
# --------------------------------------------------------------------------- #
def test_token_stream_is_unchanged(client):
    """响应体逐字节保持既有协议（[REPLY] 前缀原样透传，前端解析无需改动）。"""
    resp = post_chat(client, "你好", session_id="s1")

    assert resp.status_code == 200
    assert resp.text == "[REPLY]好的。"
    assert resp.headers["content-type"].startswith("text/plain")


def test_compat_endpoint_behaves_the_same(client):
    """/chat 兼容端点与 /chat/stream 同源，一并守住。"""
    resp = client.post("/chat", json={"message": "你好", "session_id": "s-compat"})

    assert resp.status_code == 200
    assert resp.text == "[REPLY]好的。"


# --------------------------------------------------------------------------- #
# ② 会话标识回传
# --------------------------------------------------------------------------- #
def test_session_id_is_echoed_back(client):
    resp = post_chat(client, "你好", session_id="s-echo")

    assert resp.headers["X-Session-Id"] == "s-echo"


def test_session_id_is_generated_when_absent(client):
    """不带 session_id 时服务端生成并回传，前端据此续上后续请求。"""
    resp = post_chat(client, "你好")

    generated = resp.headers.get("X-Session-Id")
    assert generated and len(generated) >= 16


# --------------------------------------------------------------------------- #
# ③ 多轮上下文接续（改道最容易静默漂移的地方）
# --------------------------------------------------------------------------- #
def test_multi_turn_context_is_carried_over(client):
    post_chat(client, "第一轮问题", session_id="s-multi")
    post_chat(client, "第二轮问题", session_id="s-multi")

    contents = [m.content for m in client.llm.last_messages]
    assert "第一轮问题" in contents      # 上一轮用户输入进了上下文
    assert "好的。" in contents          # 上一轮助手回复也进了
    assert contents[-1] == "第二轮问题"  # 本轮输入在最后

    history = ch._session_store.get_or_create("s-multi").history
    assert [(t.role, t.content) for t in history] == [
        ("user", "第一轮问题"), ("assistant", "好的。"),
        ("user", "第二轮问题"), ("assistant", "好的。"),
    ]


# --------------------------------------------------------------------------- #
# ④ 跨会话不串号
# --------------------------------------------------------------------------- #
def test_sessions_do_not_leak_into_each_other(client):
    post_chat(client, "会话A的问题", session_id="A")
    post_chat(client, "会话B的问题", session_id="B")

    contents = [m.content for m in client.llm.last_messages]
    assert "会话A的问题" not in contents
    assert contents[-1] == "会话B的问题"

    a = ch._session_store.get_or_create("A").history
    b = ch._session_store.get_or_create("B").history
    assert all("会话B" not in t.content for t in a)
    assert all("会话A" not in t.content for t in b)


# --------------------------------------------------------------------------- #
# ⑤ 回退开关
# --------------------------------------------------------------------------- #
def test_legacy_direct_path_still_works(client, monkeypatch):
    """应急回退开关关掉 executor 后，旧直调路径行为一致。"""
    monkeypatch.setattr(ch, "_EXECUTOR_ENABLED", False)

    resp = post_chat(client, "你好", session_id="s-legacy")

    assert resp.status_code == 200
    assert resp.text == "[REPLY]好的。"
    history = ch._session_store.get_or_create("s-legacy").history
    assert [t.role for t in history] == ["user", "assistant"]
