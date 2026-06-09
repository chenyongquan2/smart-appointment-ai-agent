"""评估集运行器（Phase 0）。

用法:
    uv run python evals/run_evals.py            # 跑全部用例, 输出意图准确率基线
    uv run python evals/run_evals.py --limit 5  # 只跑前 5 条(冒烟)

接入真实意图分类器(经 config.model_provider)，对每条用例跑 classify_task，
与 expected_intent 比对，输出意图分类准确率基线 + 按类目分项 + 错误清单。
成功静默、只详列错误。缺 API key 时优雅降级(提示 + 非零退出，不崩)。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Windows 中文环境控制台默认 gbk，统一转 UTF-8（与 app.py 一致）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# 让脚本能 import 项目根下的 config / agents（脚本目录是 evals/，需手动加根目录）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

CASES_FILE = Path(__file__).parent / "cases.jsonl"

# 真实分类器的 5 类口径（来源: agents/task_classification/task_classifier.py）
VALID_INTENTS = {"appointment", "query", "pay", "statistics", "other"}


def load_cases(path: Path) -> list[dict]:
    """读取 jsonl 用例; 跳过空行与 // 注释行; 校验 expected_intent 合法。"""
    cases: list[dict] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"[ERROR] 第 {lineno} 行 JSON 解析失败: {exc}", file=sys.stderr)
            raise
        intent = case.get("expected_intent")
        if intent not in VALID_INTENTS:
            print(
                f"[ERROR] 第 {lineno} 行 expected_intent={intent!r} 非法; "
                f"必须是 {sorted(VALID_INTENTS)} 之一",
                file=sys.stderr,
            )
            raise SystemExit(2)
        cases.append(case)
    return cases


def _has_api_key() -> bool:
    """按 MODEL_PROVIDER 判断对应的 API key 是否已配置。"""
    provider = (os.getenv("MODEL_PROVIDER", "azure") or "azure").strip().lower()
    key_var = "AZURE_OPENAI_API_KEY" if provider == "azure" else "LLM_API_KEY"
    return bool(os.getenv(key_var))


def print_cases(cases: list[dict]) -> None:
    """无 key 退路: 仅打印用例清单。"""
    for case in cases:
        intent = case.get("expected_intent", "?")
        text = case.get("input", "")
        print(f"  [{intent:11}] {text[:42]}")


async def run_baseline(cases: list[dict]) -> int:
    """跑真实分类器, 输出多指标报告 + 错误清单。返回进程退出码。

    Phase 6：在意图准确率之外，按用例计时（端到端延迟），并把每条用例填成
    ``EvalResult`` 交给 ``evals.metrics`` 汇总。工具调用正确率/槽位完整率仅在对应
    数据可得时计入，否则报告显式标 N/A（不伪造分母）。
    """
    import time

    from config.model_provider import create_chat_model
    from agents.task_classification.task_classifier import TaskClassifier
    from evals.metrics import EvalResult, build_report, format_report

    try:
        classifier = TaskClassifier(create_chat_model(temperature=0))
    except Exception as exc:  # 配置错误(如不支持的 provider): 报告而非崩溃
        print(f"[ERROR] 创建分类器失败: {exc}", file=sys.stderr)
        return 2

    results: list[EvalResult] = []
    by_intent: dict[str, list[int]] = {}  # intent -> [correct, total]

    for case in cases:
        text = case.get("input", "")
        expected = case["expected_intent"]
        start = time.perf_counter()
        try:
            actual = await classifier.classify_task(text)
        except Exception as exc:  # 网络/鉴权异常: 标注出来, 不中断整轮
            actual = f"<异常:{type(exc).__name__}>"
        latency = time.perf_counter() - start

        stat = by_intent.setdefault(expected, [0, 0])
        stat[1] += 1
        if actual == expected:
            stat[0] += 1

        results.append(
            EvalResult(
                input=text,
                expected_intent=expected,
                actual_intent=actual,
                # expected_tools 为前瞻注解；本运行不端到端执行 AgentLoop，故 actual_tools
                # 留空（报告会据此把"工具调用正确率"标 N/A 并注明原因）。
                expected_tools=case.get("expected_tools"),
                actual_tools=None,
                expected_slots=case.get("expected_slots"),
                actual_slots=None,
                latency_s=latency,
            )
        )

    report = build_report(results)
    print(format_report(report))

    # 按意图类目分项（保留 Phase 0 的分类目视图）。
    print("\n按类目（意图）:")
    for intent in sorted(by_intent):
        c, t = by_intent[intent]
        print(f"  {intent:11} {c}/{t}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="评估集运行器 (Phase 0)")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条(冒烟)")
    args = parser.parse_args()

    if not CASES_FILE.exists():
        print(f"[ERROR] 找不到用例文件: {CASES_FILE}", file=sys.stderr)
        return 1

    cases = load_cases(CASES_FILE)
    if args.limit is not None:
        cases = cases[: args.limit]
    print(f"已加载 {len(cases)} 条评估用例 ({CASES_FILE.name})")

    if not _has_api_key():
        print(
            "\n[提示] 未检测到 API key(MODEL_PROVIDER 对应的 *_API_KEY 未配置)。\n"
            "       无法产出准确率基线; 以下仅为用例清单。\n"
            "       在 .env 配好后重跑: uv run python evals/run_evals.py",
            file=sys.stderr,
        )
        print_cases(cases)
        return 2

    return asyncio.run(run_baseline(cases))


if __name__ == "__main__":
    raise SystemExit(main())
