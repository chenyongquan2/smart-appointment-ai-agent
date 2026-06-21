"""第 3 站「记忆」真实流程调试脚本（用真实 LLM，验证记忆真的串起来）。

与 scripts/debug_memory_flow.py 的区别：那个用离线 fake LLM（确定性、不触网）；
这个用 **真实的 `_agent_loop`（真 LLM，按 .env 配置调用真模型）**，跑一条真流程。

验证思路（经典「名字记忆」测试，不触发预约/写库）：
  第 1 轮：告诉它「我叫小王」
  第 2 轮：问它「我叫什么名字？」——真实模型若答出「小王」，说明短期记忆确实把第 1 轮喂回了。

每轮打印：① 进来时 history → ② 本轮将注入的短期消息/长期偏好 → ③ 真实模型回复 → ④ history 变化。

默认用「内存 SessionStore」以免写你的真实对话 DB（记忆逻辑完全相同，只是不落库）。
想用「完全真实」含 DB 持久化的路径，把下面 USE_IN_MEMORY_SESSION 改成 False。

跑：  uv run python scripts/debug_memory_flow_real.py
注意：会真实调用 LLM（消耗额度、走网络），这是你已确认要的。
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import api.chat_handler as ch
from harness.runtime.session import SessionStore

# True = 内存会话（不写真实 DB，干净）；False = 用 chat_handler 原本的真实 DB 会话（含持久化）。
USE_IN_MEMORY_SESSION = True


def _hist(sid: str):
    return [(t.role, t.content) for t in ch._session_store.get_or_create(sid).history]


def _banner(text: str) -> None:
    print("\n" + "=" * 72 + f"\n{text}\n" + "=" * 72)


async def run_turn(sid: str, turn_no: int, msg: str) -> None:
    _banner(f"[session={sid}] 第 {turn_no} 轮：用户说「{msg}」")

    # ① 本轮开始前的 history（短期记忆的料）
    print("① 进来时 history :", _hist(sid))

    # ② 复算 chat_handler 内部「将注入 loop」的记忆（取历史在写本轮输入之前，与真实顺序一致）
    state = ch._session_store.get_or_create(sid)
    injected = ch._short_term.to_messages(state.history)
    hint = ch._long_term.build_preference_hint(state.user_id)
    print("② 本轮将注入的短期消息（history）：")
    if not injected:
        print("     （空——这是本会话第一轮）")
    for m in injected:
        print(f"     [{type(m).__name__}] {m.content!r}")
    print("   长期偏好 hint :", repr(hint) if hint else "（空——该用户暂无偏好）")

    # ③ 真实驱动（真 LLM）。流式收集，挑出 [REPLY] 最终回复。
    reply = ""
    async for token in ch.ProcessUserInput_stream(msg, session_id=sid):
        if token.startswith("[REPLY]"):
            reply = token[len("[REPLY]"):]
    print("③ 真实模型回复   :", reply)

    # ④ 本轮结束后的 history
    print("④ 结束时 history :", _hist(sid))


async def main() -> None:
    from config.model_provider import get_model_provider

    if USE_IN_MEMORY_SESSION:
        ch._session_store = SessionStore(repo=None)  # 内存会话，避免写真实 DB

    print(f"模型 provider = {get_model_provider()} ；模型 = {os.getenv('LLM_MODEL')}")
    print("（下面每轮都会真实调用 LLM）")

    sid = "real-demo-1"
    await run_turn(sid, 1, "你好，我叫小王。")
    await run_turn(sid, 2, "我叫什么名字？")  # ← 模型答出「小王」= 短期记忆把第 1 轮喂回了


if __name__ == "__main__":
    asyncio.run(main())
