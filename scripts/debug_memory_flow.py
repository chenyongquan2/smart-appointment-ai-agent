"""第 3 站「记忆」完整调试脚本（离线、无需 API key、确定性）。

目的：把 chat_handler 的记忆编排「跑起来 + 打印每步状态」，对照 docs 第 3 站 3.5
（两轮对话的记忆流动）与 3.8（它在项目里的位置）。

它做了什么：
- 用 CapturingModel 顶替真 LLM（不触网；记录每次收到的 messages，固定回一句）；
- 用内存 SessionStore（repo=None）、FakePrefRepo（伪造长期偏好），故全程离线、可复现；
- 跑两轮「同一 session」对话，看短期记忆把上一轮喂回 + 长期偏好进系统提示；
- 再跑一次「另一个 session」，看会话隔离。

怎么用：
- 直接看输出：  uv run python scripts/debug_memory_flow.py
- 单步调试：    VS Code 用「Python: 调试当前文件」打开本文件按 F5；
              想看记忆编排，在 api/chat_handler.py 的 92/97/98/102/107/122 行打断点
              （断点会被两轮各命中一次，正好看 history 长大）。

注：本脚本是第 3 站的配套调试教材，被 docs/harness-code-reading.md 的 3.7「动线 D」引用；
    删除前请一并清理该处链接。
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, List, Optional

# 让脚本能 import 仓库根下的 api/ 与 harness/（python 默认只把脚本所在的 scripts/ 加进路径）。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 终端默认 GBK，会把 UTF-8 中文打成乱码——强制 stdout 用 UTF-8。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import api.chat_handler as ch
from harness.memory.long_term import LongTermMemory
from harness.memory.short_term import ShortTermMemory
from harness.runtime import AgentLoop
from harness.runtime.session import SessionStore
from harness.tools.registry import ToolRegistry


class CapturingModel(BaseChatModel):
    """离线假 LLM：记录每次收到的 messages，固定回一句话（不触网、不调工具）。"""

    reply: str = "好的，已为您记录。"
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
        # ☜ 关键：把「这一轮 loop 实际喂给模型的 messages」记下来，供下面打印对照
        object.__setattr__(self, "last_messages", list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.reply))])


class FakePrefRepo:
    """伪造的长期偏好仓库：让 LongTermMemory 有东西可读（演示偏好注入）。"""

    def get_user_preferences(self, user_id: str):
        return [
            {"preference_type": "technician", "preference_value": "张三", "confidence_score": 5},
            {"preference_type": "duration", "preference_value": "60分钟", "confidence_score": 4},
        ]


def _hist(store: SessionStore, sid: str):
    return [(t.role, t.content) for t in store.get_or_create(sid).history]


def _banner(text: str) -> None:
    print("\n" + "=" * 72 + f"\n{text}\n" + "=" * 72)


async def run_turn(llm: CapturingModel, sid: str, turn_no: int, msg: str) -> None:
    _banner(f"[session={sid}] 第 {turn_no} 轮：用户说「{msg}」")

    # ① 本轮开始前，这个会话的 history（短期记忆的料）
    print("① 进来时 history :", _hist(ch._session_store, sid))

    # ④ 驱动 chat_handler（内部：取记忆 → 写用户输入 → loop.run → 回写回复）
    out = "".join([tok async for tok in ch.ProcessUserInput_stream(msg, session_id=sid)])

    # 看「这一轮 LLM 实际收到的 messages」——记忆是否被喂回，一目了然
    print("④ LLM 实际收到的 messages：")
    for m in llm.last_messages:
        tag = type(m).__name__
        if tag == "SystemMessage":
            # 系统提示很长，只点出关键：是否带了「长期偏好 suffix」（这就是长期记忆的注入点）
            c = str(m.content)
            if "历史偏好" in c:
                suffix = "已知该用户的" + c.split("已知该用户的", 1)[1]
                print(f"     [SystemMessage] 行为纲领 + 长期偏好 → {suffix!r}")
            else:
                print(f"     [SystemMessage] 行为纲领（无长期偏好）")
        else:
            print(f"     [{tag}] {m.content!r}")

    print("⑤ 本轮回复       :", out)
    print("⑥ 结束时 history :", _hist(ch._session_store, sid))


async def main() -> None:
    # —— 把 chat_handler 的模块级单例换成离线 fake（等价于 e2e 测试的 fixture，但加了假偏好）——
    llm = CapturingModel()
    ch._agent_loop = AgentLoop(llm=llm, registry=ToolRegistry())   # 空工具集：聚焦记忆，不掺工具
    ch._session_store = SessionStore(repo=None)                    # 纯内存：可复现
    ch._short_term = ShortTermMemory(window_turns=10)              # 短期窗口 10 轮
    ch._long_term = LongTermMemory(FakePrefRepo())                 # 长期偏好：有料可读

    # —— A. 同一 session 两轮：看短期记忆把第 1 轮喂回 + 长期偏好进系统提示 ——
    await run_turn(llm, "demo-1", 1, "我想约明天下午的肩颈按摩")
    await run_turn(llm, "demo-1", 2, "改成后天")

    # —— B. 换一个 session：看会话隔离（B 看不到 demo-1 的任何内容）——
    await run_turn(llm, "demo-2", 1, "你们几点关门？")

    _banner("两个会话最终各自的 history（互不串号 = 会话隔离）")
    print("demo-1 :", _hist(ch._session_store, "demo-1"))
    print("demo-2 :", _hist(ch._session_store, "demo-2"))


if __name__ == "__main__":
    asyncio.run(main())
