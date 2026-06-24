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
# 不转的话，打印中文用例/报告可能抛 UnicodeEncodeError。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):  # 老 Python 的流没有 reconfigure，先判断再调
        _stream.reconfigure(encoding="utf-8")

# 让脚本能 import 项目根下的 config / agents（脚本目录是 evals/，需手动加根目录）
# __file__ 是本脚本路径；.parent.parent 上跳两级到项目根，插到 sys.path 最前确保优先命中。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402  （此 import 必须在上面改完 sys.path「之后」，故压 E402）

load_dotenv()  # 读 .env 里的 API key / MODEL_PROVIDER 等到环境变量

CASES_FILE = Path(__file__).parent / "cases.jsonl"  # 用例文件与本脚本同目录

# 真实分类器的 5 类口径（来源: agents/task_classification/task_classifier.py）
# 加载用例时据此校验 expected_intent 合法——防手滑写错类名，问题尽早暴露。
VALID_INTENTS = {"appointment", "query", "pay", "statistics", "other"}


def load_cases(path: Path) -> list[dict]:
    """读取 jsonl 用例; 跳过空行与 // 注释行; 校验 expected_intent 合法。"""
    # jsonl = 「每行一个独立 JSON 对象」的格式（不是整个文件一个 JSON 数组），故逐行解析。
    cases: list[dict] = []
    # enumerate(..., 1)：行号从 1 起，报错时给出的行号与编辑器一致，便于定位。
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("//"):  # 跳过空行和 // 注释行（jsonl 本不支持注释，这里自定义放宽）
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            # 解析失败「不静默跳过」：报出行号后 re-raise，让坏数据立刻可见而非悄悄漏测。
            print(f"[ERROR] 第 {lineno} 行 JSON 解析失败: {exc}", file=sys.stderr)
            raise
        intent = case.get("expected_intent")
        if intent not in VALID_INTENTS:  # 类名写错（如 typo）直接判非法
            print(
                f"[ERROR] 第 {lineno} 行 expected_intent={intent!r} 非法; "
                f"必须是 {sorted(VALID_INTENTS)} 之一",
                file=sys.stderr,
            )
            raise SystemExit(2)  # 退出码 2：约定的「用例/配置错误」码（见 main 的各处 return 2）
        cases.append(case)
    return cases


def _has_api_key() -> bool:
    """按 MODEL_PROVIDER 判断对应的 API key 是否已配置。"""
    # 不同 provider 用不同的 key 环境变量名，先看用的是哪家再查对应那把 key。
    provider = (os.getenv("MODEL_PROVIDER", "azure") or "azure").strip().lower()
    key_var = "AZURE_OPENAI_API_KEY" if provider == "azure" else "LLM_API_KEY"
    return bool(os.getenv(key_var))  # 只判「有没有配」，不验证 key 真伪（真伪留给真正调用时暴露）


def print_cases(cases: list[dict]) -> None:
    """无 key 退路: 仅打印用例清单。"""
    for case in cases:
        intent = case.get("expected_intent", "?")
        text = case.get("input", "")
        print(f"  [{intent:11}] {text[:42]}")


async def _run_once(cases, classifier, llm, full_registry, subagents, capture_fn, judge_fn=None):
    """跑一遍全部用例，返回填好的 ``EvalResult`` 列表（多采样时被调用 N 次）。

    单次的「跑分类器 + 端到端真跑采集(工具+回复) + 可选 judge」逻辑都收敛在这里，故
    N=1 与 N>1 走同一条路，口径完全一致。``capture_fn`` 返回 ``CaptureResult``（工具+回复）；
    ``judge_fn`` 非 None 时对回复做质量裁决（改造 4），缺省不评（回复质量记 N/A）。
    """
    import time

    results = []
    for case in cases:
        text = case.get("input", "")
        expected = case["expected_intent"]
        start = time.perf_counter()  # perf_counter：高精度单调钟，专用于测耗时
        try:
            actual = await classifier.classify_task(text)  # ← 真正调用 LLM 分类
        except Exception as exc:  # 网络/鉴权异常: 标注出来, 不中断整轮（一条挂了别拖垮全量）
            actual = f"<异常:{type(exc).__name__}>"
        latency = time.perf_counter() - start  # 仅计分类器单次调用（与既有口径一致，不含 loop）

        # 端到端真跑：构造带 tracer 的主 loop（主→delegate→子 Agent），采集工具序列 + 最终回复。
        # 与分类器并存——意图准确率不依赖真跑。单条失败不拖垮全量。
        actual_tools = None
        judge_passed = None
        try:
            cap = await capture_fn(text, llm, full_registry, subagents)  # CaptureResult
            actual_tools = cap.tool_calls
            # 回复质量 judge（改造 4）：仅在开启时对采集到的最终回复裁决。
            if judge_fn is not None:
                verdict = await judge_fn(text, cap.reply, llm)
                judge_passed = verdict.passed
        except Exception as exc:  # 真跑异常: 该条工具/judge 记 None（指标对该条标 N/A，不伪造）
            print(f"[WARN] 用例端到端真跑失败({type(exc).__name__})，工具/质量对该条记 N/A: {text[:30]}",
                  file=sys.stderr)

        # 把这条用例的「实际值」装进 EvalResult，交给 metrics 模块统一算分。
        results.append(
            _EvalResult(
                input=text,
                expected_intent=expected,
                actual_intent=actual,
                # actual_tools 采全为有序 [{name, args}]；指标只比名字集合（采全比松）。
                # 真跑失败/无工具时为 None/[]，报告据此对该条标 N/A 而非伪造分母。
                expected_tools=case.get("expected_tools"),
                actual_tools=actual_tools,
                expected_tool_args=case.get("expected_tool_args"),  # 参数级比对标注（可选）
                expected_slots=case.get("expected_slots"),
                actual_slots=None,
                latency_s=latency,
                judge_passed=judge_passed,  # 回复质量裁决（改造 4）；未开 --judge 时 None→N/A
            )
        )
    return results


def _print_by_intent(results) -> None:
    """按意图类目分项打印 correct/total（保留 Phase 0 的分类目视图，仅单次跑用）。"""
    by_intent: dict[str, list[int]] = {}
    for r in results:
        stat = by_intent.setdefault(r.expected_intent, [0, 0])
        stat[1] += 1
        if r.actual_intent == r.expected_intent:
            stat[0] += 1
    print("\n按类目（意图）:")
    for intent in sorted(by_intent):
        c, t = by_intent[intent]
        print(f"  {intent:11} {c}/{t}")


# 模块级占位：真正的 EvalResult 在 run_baseline 内按需 import 后赋给它（避免无 key 路径触碰重依赖）。
_EvalResult = None


async def run_baseline(cases: list[dict], samples: int = 1, judge: bool = False) -> int:
    """跑真实分类器 + 端到端真跑, 输出多指标报告。返回进程退出码。

    ``samples<=1``：单次跑，输出多指标报告 + 判错清单 + 按类目视图（与既有一致）。
    ``samples>1``（改造 3）：整套用例独立重跑 N 次，对每个聚合指标输出 ``mean ± 95% t-CI``。
    ``judge=True``（改造 4）：对每条 agent 最终回复跑 LLM-judge，产出回复质量通过率
    （judge 未与人工校准前报告标「未校准」）。
    """
    # 这些 import 放在函数内（而非文件顶部）：只有「确认要真跑」时才加载重依赖，
    # 也让无 key 的纯清单路径（main 里的 print_cases）不必触碰 provider/分类器。
    from config.model_provider import create_chat_model
    from agents.task_classification.task_classifier import TaskClassifier
    from evals.metrics import (
        EvalResult,
        build_report,
        format_report,
        aggregate_runs,
        format_multisample_report,
    )
    from evals.agent_capture import run_and_capture
    from evals.judge import judge_response
    from harness.subagents import build_default_subagent_registry
    from harness.tools.registry import build_default_registry

    global _EvalResult
    _EvalResult = EvalResult  # 供 _run_once 构造（避免它再触发一次重 import）

    try:
        llm = create_chat_model(temperature=0)  # temperature=0：贴生产 + 量残余抖动（改造 3）；judge 同用
        classifier = TaskClassifier(llm)
        # 端到端真跑所需：全量工具 + 子 Agent 注册中心（每条用例现场拼带 tracer 的主 loop）。
        full_registry = build_default_registry()
        subagents = build_default_subagent_registry()
    except Exception as exc:  # 配置错误(如不支持的 provider): 报告而非崩溃
        print(f"[ERROR] 创建分类器/工具失败: {exc}", file=sys.stderr)
        return 2

    judge_fn = judge_response if judge else None  # 改造 4：开启时对回复做质量裁决
    if judge:
        print("[提示] 已开启 LLM-judge 评回复质量；judge 与 agent 同模型，未经人工校准 → "
              "报告将标「未校准」，结果仅供参考（自我偏好等偏差未验证）。", file=sys.stderr)

    # ── 单次跑（默认，向后兼容）：报告不含 CI 列 ──────────────────────────────
    if samples <= 1:
        results = await _run_once(cases, classifier, llm, full_registry, subagents, run_and_capture, judge_fn)
        print(format_report(build_report(results)))
        _print_by_intent(results)
        return 0

    # ── 多采样（改造 3）：整套重跑 N 次 → 聚合 mean ± t-CI ────────────────────
    reports = []
    for i in range(samples):
        print(f"[采样 {i + 1}/{samples}] 跑整套用例…", file=sys.stderr)
        results = await _run_once(cases, classifier, llm, full_registry, subagents, run_and_capture, judge_fn)
        reports.append(build_report(results))  # 每次跑的聚合指标快照
    # aggregate_runs/format_multisample_report 是纯函数（吃 N 份报告 → mean±CI），与采样循环解耦。
    print(format_multisample_report(aggregate_runs(reports), samples, len(cases)))
    return 0  # 0 = 正常跑完（哪怕某些用例判错，「跑完」本身就算成功）


def main() -> int:
    # 返回 int 退出码（而非直接 sys.exit）：逻辑可单测，退出动作交给最底下的入口统一做。
    parser = argparse.ArgumentParser(description="评估集运行器 (Phase 0)")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条(冒烟)")
    parser.add_argument(
        "--samples", type=int, default=1,
        help="整套用例重跑次数(改造 3)；>1 时输出 mean±95%% t-CI 量化 run-to-run 抖动；默认 1(单次,不烧钱)",
    )
    parser.add_argument(
        "--judge", action="store_true",
        help="开启 LLM-judge 评回复质量(改造 4)；每条额外一次 LLM 调用；默认关。judge 未校准会在报告标注",
    )
    args = parser.parse_args()

    if not CASES_FILE.exists():
        print(f"[ERROR] 找不到用例文件: {CASES_FILE}", file=sys.stderr)
        return 1  # 1 = 环境/文件缺失

    cases = load_cases(CASES_FILE)
    if args.limit is not None:
        cases = cases[: args.limit]  # 冒烟模式：只截前 N 条快速验证流程通不通
    print(f"已加载 {len(cases)} 条评估用例 ({CASES_FILE.name})")

    # ★ 优雅降级：没配 key 就「不报错崩溃」，而是退而只打印用例清单 + 怎么配的提示。
    #   这样没 key 的人也能看到评估集长啥样，且 return 2 让 CI 能区分「真跑过」与「跳过了」。
    if not _has_api_key():
        print(
            "\n[提示] 未检测到 API key(MODEL_PROVIDER 对应的 *_API_KEY 未配置)。\n"
            "       无法产出准确率基线; 以下仅为用例清单。\n"
            "       在 .env 配好后重跑: uv run python evals/run_evals.py",
            file=sys.stderr,
        )
        print_cases(cases)
        return 2  # 2 = 优雅降级（没真跑分类器）

    # 有 key：进入真正的异步评估。asyncio.run 负责建/关事件循环跑这个协程。
    return asyncio.run(run_baseline(cases, samples=args.samples, judge=args.judge))


if __name__ == "__main__":
    # 作为脚本直接运行时的入口；把 main 的返回码交给 SystemExit → 即进程退出码（供 shell/CI 判定）。
    raise SystemExit(main())
