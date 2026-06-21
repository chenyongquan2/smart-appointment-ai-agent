"""记忆压缩质量对照（add-context-compaction，独立 eval，不进 pytest 主回归）。

用法:
    uv run python evals/eval_compaction.py

为何独立于 pytest：本 eval 调**真 LLM**、结果非确定，违背单测「确定性、不触网」铁律，
故按项目约定放 evals/ 单独跑（机制由 tests/test_summary_memory.py 用 fake LLM 确定性覆盖）。

验证的核心质量主张（design.md D3/D9）：把含早期约束的较旧回合压缩为摘要后，
**关键约束/未完成槽位不丢失**——这正是结构化摘要相对自由文本摘要的价值。
成功静默、只报失败；缺 API key 时优雅降级（提示 + 非零退出，不崩）。
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()


def _has_api_key() -> bool:
    provider = (os.getenv("MODEL_PROVIDER", "azure") or "azure").strip().lower()
    key_var = "AZURE_OPENAI_API_KEY" if provider == "azure" else "LLM_API_KEY"
    return bool(os.getenv(key_var))


# 早期约束 + 一批填充回合（模拟会话变长、早期约束滑出短期窗口）。
_OLD_TURNS = [
    {"id": 1, "role": "user", "content": "我想预约按摩，但我只要女技师，而且只能安排在周末。"},
    {"id": 2, "role": "assistant", "content": "好的，已记下：女技师、周末。请问您想约哪个项目？"},
    {"id": 3, "role": "user", "content": "我想做推拿，时长 60 分钟。"},
    {"id": 4, "role": "assistant", "content": "好的，推拿 60 分钟。还有其他要求吗？"},
    {"id": 5, "role": "user", "content": "顺便问下你们营业到几点？"},
    {"id": 6, "role": "assistant", "content": "我们营业到晚上 10 点。"},
    {"id": 7, "role": "user", "content": "那帮我看看本周六下午有没有空。"},
    {"id": 8, "role": "assistant", "content": "好的，我查一下本周六下午的安排。"},
]


async def _run() -> int:
    from config.model_provider import create_chat_model
    from harness.memory.summary import LLMSummaryMemory

    try:
        llm = create_chat_model(temperature=0)
    except Exception as exc:  # 配置错误：报告而非崩溃
        print(f"[ERROR] 创建模型失败: {exc}", file=sys.stderr)
        return 2

    # repos 传 None：summarize() 是纯 LLM 步骤，不触碰持久层（持久/缓存逻辑在 compact_if_needed）。
    mem = LLMSummaryMemory(llm=llm, conversations_repo=None, summaries_repo=None)

    failures: list[str] = []

    # ① 单次压缩：早期约束应完整保留在摘要里。
    summary = await mem.summarize(_OLD_TURNS)
    print("=== 单次压缩摘要 ===")
    print(summary)
    if "女" not in summary:
        failures.append("摘要丢失了『女技师』约束")
    if "周末" not in summary and "周六" not in summary:
        failures.append("摘要丢失了『周末』时间约束")

    # ② 滚动压缩：在前序摘要基础上并入新回合，早期约束仍不能丢。
    new_turns = [
        {"id": 9, "role": "user", "content": "对了，我预算不超过 300 元。"},
        {"id": 10, "role": "assistant", "content": "好的，预算 300 元以内。"},
    ]
    rolled = await mem.summarize(new_turns, prior_summary=summary)
    print("\n=== 滚动压缩摘要 ===")
    print(rolled)
    if "女" not in rolled:
        failures.append("滚动后丢失了『女技师』约束")
    if "预算" not in rolled and "300" not in rolled:
        failures.append("滚动后丢失了新并入的『预算』约束")

    if failures:
        print("\n[FAIL] 压缩质量对照未通过：", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("\n[OK] 压缩质量对照通过：早期约束与新并入约束均被保留。")
    return 0


def main() -> int:
    if not _has_api_key():
        print(
            "[提示] 未检测到 API key（MODEL_PROVIDER 对应的 *_API_KEY 未配置）。\n"
            "       本 eval 需真 LLM，无法运行。配好 .env 后重跑：\n"
            "       uv run python evals/eval_compaction.py",
            file=sys.stderr,
        )
        return 2
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
