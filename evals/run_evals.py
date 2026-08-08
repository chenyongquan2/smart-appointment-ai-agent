"""评估集运行器（Phase 0）。

用法:
    uv run python evals/run_evals.py            # 跑全部用例, 输出多指标报告
    uv run python evals/run_evals.py --limit 5  # 只跑前 5 条(冒烟)

对每条用例端到端真跑生产路径的 AgentLoop（主→delegate→子 Agent），采集工具序列/
槽位/最终回复并汇总多指标报告。成功静默、只详列错误。缺 API key 时优雅降级
(提示 + 非零退出，不崩)。

（change retire-legacy-intent-classifier）旧意图分类器已退役：意图理解由工具选择体现、
被工具级指标覆盖；expected_intent 仅作数据集标签（加载校验/构成约束）保留。

退出码契约（CI/闸门 2 据此判定）:
    0 = 正常跑完（哪怕个别用例判错，"跑完"即成功）
    1 = 环境/文件缺失（含 --gate 时基线文件不存在）
    2 = 用例非法 / 无 API key 优雅降级 / --gate 与 --update-baseline 互斥
    3 = 检测到回归（改造 6：--gate 模式下被守指标低于基线−容差）

回归门禁（改造 6）:
    --update-baseline  把本次跑分落盘为基线（当前域的 evals/baseline.json）
    --gate             跑完比对基线，被守指标回归则以退出码 3 结束
    --tolerance        容差（默认 0.30）吸收 LLM 抖动；门禁只守正确性子集，
                       **守哪几项由领域包声明**（Domain.eval_profile.gated_metrics，
                       change oncall-evals-bootstrap）：预约域守 工具调用-F1 / 槽位完整率，
                       值守域守 工具调用-F1 / 参数级F1。延迟与回复质量任何域都不准守。

容差 0.30 的依据（change retire-legacy-intent-classifier 重定基线时实测）：当前模型
(deepseek-v4-flash)工具触发 run-to-run 抖动实测 t-CI 半宽——工具 F1 ±5.7pp、
**槽位抽取完整率 ±28.7pp**（n=3，干净跑）。槽位半宽超出原 0.20，故按实测上调至 0.30 覆盖
最差半宽（spec 要求容差覆盖观测半宽、不得是无凭据魔数）。代价：门禁更松，只拦得住
「大幅回归」。治本方向是补预约锚点压低槽位方差（数据集冗余，另立 change），届时可回调。
详见 evals/README.md。

dev / held-out 切分（改造 8 切片 · change evals-dataset-scaleup-heldout）:
    默认只评 dev 子集（未标 split 字段的既有用例也归 dev，向后兼容）。
    --include-heldout  连同 held-out 一起评，分集呈现，MUST NOT 混入 dev 基线
    --heldout-only      只评 held-out（过拟合体检）；不可与 --update-baseline/--gate 同用
    基线/门禁恒基于 dev 子集，详见 evals/README.md。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from functools import partial
from pathlib import Path
from typing import Collection

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
from domains import load_domain

load_dotenv()  # 读 .env 里的 API key / MODEL_PROVIDER 等到环境变量

# 评估**数据与标注口径**随领域包走，**机制**（本脚本、采集、triage、并发 runner、指标
# 算法、门禁比对）留在 evals/ 且域无关。
# ⚠ 修正一条曾经的乐观说法：domain-packages 的 design D7 说「建 oncall 用例集时本脚本
# 一行不用改」——实际不成立。彼时本模块与 metrics 里还硬编码着 5 类预约意图、预约槽位名
# 与门禁指标组合，装上另一个域的数据会直接加载失败或让门禁**静默**少守一项。
# change oncall-evals-bootstrap 把这三项收进 Domain.eval_profile 后，分界才真正成立。
_DOMAIN = load_domain()
_EVALS_DIR = _DOMAIN.evals_dir
CASES_FILE = _EVALS_DIR / "cases.jsonl"
BASELINE_FILE = _EVALS_DIR / "baseline.json"  # 回归门禁基线（改造 6）

# 评估标注口径（标签白名单 / 槽位键映射 / 门禁指标集）**随域声明**
# （change oncall-evals-bootstrap）。此前这三项写死在本模块与 metrics 里，装上另一个域
# 的数据要么直接加载失败（标签白名单），要么门禁静默退化成守更少的项。
_EVAL_PROFILE = _DOMAIN.eval_profile

# 用例并发度默认值（change evals-concurrent-runner D2）：保守取 5——每条用例内部还会派生
# 子 Agent，实际在途请求是并发数的数倍；网关限流阈值未知（重定基线时实测到过 503 与连接错误）。
# 5 已能把 41 条的单次跑从约 18 分钟压到几分钟，收益大头已拿到；实测稳定后可再调高。
DEFAULT_CONCURRENCY = 5

# 用例集 dev/held-out 切分（change evals-dataset-scaleup-heldout）：
# dev = 日常调试/调优/门禁用；held-out = 过拟合体检的留出集，MUST NOT 参与调优与门禁。
# 缺省(未标 split 字段)即 dev——既有用例不改一字即属 dev，向后兼容。
VALID_SPLITS = {"dev", "held-out"}


def load_cases(path: Path, labels: Collection[str] | None = None) -> list[dict]:
    """读取 jsonl 用例; 跳过空行与 // 注释行; 校验 expected_intent 合法。

    Args:
        path: 用例文件。
        labels: 合法标签白名单，由当前领域包声明（``eval_profile.labels``）。缺省取
            装载域的声明——本模块不再内置任何具体领域的标签名。
    """
    valid = set(labels) if labels is not None else set(_EVAL_PROFILE.labels)
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
        if intent not in valid:  # 类名写错（如 typo）直接判非法
            print(
                f"[ERROR] 第 {lineno} 行 expected_intent={intent!r} 非法; "
                f"必须是 {sorted(valid)} 之一",
                file=sys.stderr,
            )
            raise SystemExit(2)  # 退出码 2：约定的「用例/配置错误」码（见 main 的各处 return 2）
        # 用例「输入」支持单轮 input(字符串) 与多轮 turns(字符串列表) 两形态，二者互斥。
        # 归一：给每条用例补一个 case["turns"]=list[str]（单轮 input → 单元素列表），
        # 让下游 _run_once 统一按 turns 处理，单轮等价单元素 turns。
        case["turns"] = _normalize_turns(case, lineno)
        # 集归属（dev/held-out）：缺省填 dev，非法值报行号——与 expected_intent 的白名单
        # 校验同一范式（坏数据不静默）。归一后下游总能读到 case["split"]。
        split = case.get("split", "dev")
        if split not in VALID_SPLITS:
            print(
                f"[ERROR] 第 {lineno} 行 split={split!r} 非法; 必须是 {sorted(VALID_SPLITS)} 之一",
                file=sys.stderr,
            )
            raise SystemExit(2)
        case["split"] = split
        cases.append(case)
    return cases


def _filter_by_split(
    cases: list[dict], *, include_heldout: bool = False, heldout_only: bool = False
) -> list[dict]:
    """按 dev/held-out 开关过滤用例（纯函数）。

    默认(两开关都 False)只留 dev——与本变更前的默认行为等价。``heldout_only`` 只留
    held-out；``include_heldout`` 留 dev+held-out 全部。二者由调用方保证互斥。
    """
    if heldout_only:
        return [c for c in cases if c["split"] == "held-out"]
    if include_heldout:
        return list(cases)
    return [c for c in cases if c["split"] == "dev"]


def _split_results(cases: list[dict], results: list) -> tuple[list, list]:
    """按用例集归属把同序的 ``results`` 拆成 ``(dev, held-out)``（纯函数）。

    ``results`` 与 ``cases`` 须同序同长（``_run_once`` 保证）。held-out 的结果绝不混入
    dev 侧——门禁/基线只读 dev 侧返回值，物理上就拿不到 held-out 数据。
    """
    dev = [r for c, r in zip(cases, results) if c["split"] == "dev"]
    heldout = [r for c, r in zip(cases, results) if c["split"] == "held-out"]
    return dev, heldout


def _normalize_turns(case: dict, lineno: int) -> list[str]:
    """把用例的 input/turns 归一为 turns 列表；校验互斥与类型。

    一条用例 MUST 恰好提供 input 或 turns 之一：两者皆有/皆无都报行号 SystemExit(2)
    （与「坏用例不静默」一致）。多轮 turns SHALL 为非空字符串列表。
    """
    has_input = "input" in case
    has_turns = "turns" in case
    if has_input == has_turns:  # 同真(都给)或同假(都缺)都非法
        which = "同时提供了 input 与 turns" if has_input else "既无 input 也无 turns"
        print(f"[ERROR] 第 {lineno} 行 {which}; 必须恰好提供其一", file=sys.stderr)
        raise SystemExit(2)
    if has_input:
        text = case["input"]
        if not isinstance(text, str):
            print(f"[ERROR] 第 {lineno} 行 input 必须是字符串", file=sys.stderr)
            raise SystemExit(2)
        return [text]
    turns = case["turns"]
    if not isinstance(turns, list) or not turns or not all(isinstance(t, str) for t in turns):
        print(f"[ERROR] 第 {lineno} 行 turns 必须是非空字符串列表", file=sys.stderr)
        raise SystemExit(2)
    return turns


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
        turns = case.get("turns") or [case.get("input", "")]
        text = turns[0]
        suffix = f" (+{len(turns) - 1}轮)" if len(turns) > 1 else ""  # 多轮用例标注轮数
        print(f"  [{intent:11}] {text[:42]}{suffix}")


async def _run_case(case, llm, full_registry, subagents, capture_fn,
                    judge_fn=None, capture_multiturn_fn=None):
    """跑**单条**用例并返回填好的 ``EvalResult``（并发化后的最小执行单元）。

    ``capture_fn`` 返回 ``CaptureResult``（工具+回复）；``judge_fn`` 非 None 时对回复做质量
    裁决（改造 4），缺省不评（回复质量记 N/A）。

    多轮（change evals-multiturn-cases）：用例的输入经 ``load_cases`` 归一为 ``case["turns"]``
    （单轮=单元素列表）。采集按轮长分派——单轮走 ``capture_fn``（路径不变），
    多轮走 ``capture_multiturn_fn``（按轮驱动、跨轮累计工具/槽位、末轮回复喂 judge）。

    延迟口径（change retire-legacy-intent-classifier）：计端到端真跑全程耗时
    （多轮为跨轮累计），不再是旧分类器单次调用耗时。并发跑时该耗时含资源竞争
    （change evals-concurrent-runner D4：如实标注、不做补偿估算）。

    【失败隔离】本函数**内部吞掉**真跑异常（记 N/A），故并发时 ``gather`` 收不到异常、
    不会取消其它在途用例——这是"单条失败不拖垮全量"在并发下的落点。
    """
    import time

    turns = case["turns"]  # load_cases 已归一为非空 list[str]
    first_turn = turns[0]

    # 端到端真跑：构造带 tracer 的主 loop（主→delegate→子 Agent），采集工具序列 + 最终回复。
    # 每条用例一个独立 exporter 沙盒（见 agent_capture 的 _build_capture_loop），故并发安全。
    actual_tools = None
    actual_tool_outcomes = None
    judge_passed = None
    start = time.perf_counter()  # perf_counter：高精度单调钟，专用于测耗时
    try:
        if len(turns) > 1 and capture_multiturn_fn is not None:
            cap = await capture_multiturn_fn(turns, llm, full_registry, subagents)
        else:
            cap = await capture_fn(first_turn, llm, full_registry, subagents)  # 单轮路径不变
        latency = time.perf_counter() - start  # 端到端真跑耗时（judge 是评测开销，不计入）
        actual_tools = cap.tool_calls
        actual_tool_outcomes = cap.tool_outcomes  # 工具执行成败（任务成功率用）
        # 回复质量 judge（改造 4）：仅在开启时对采集到的最终回复裁决（多轮用首轮作问题、末轮回复作答）。
        if judge_fn is not None:
            verdict = await judge_fn(first_turn, cap.reply, llm)
            judge_passed = verdict.passed
    except Exception as exc:  # 真跑异常: 该条工具/judge 记 None（指标对该条标 N/A，不伪造）
        latency = None  # 真跑失败没有可信的端到端耗时，标 N/A 而非记半截时间
        print(f"[WARN] 用例端到端真跑失败({type(exc).__name__})，工具/质量对该条记 N/A: {first_turn[:30]}",
              file=sys.stderr)

    # 把这条用例的「实际值」装进 EvalResult，交给 metrics 模块统一算分。
    return _EvalResult(
        input=first_turn,
        # actual_tools 采全为有序 [{name, args}]；指标只比名字集合（采全比松）。
        # 真跑失败/无工具时为 None/[]，报告据此对该条标 N/A 而非伪造分母。
        expected_tools=case.get("expected_tools"),
        actual_tools=actual_tools,
        expected_tool_args=case.get("expected_tool_args"),  # 参数级比对标注（可选）
        expected_slots=case.get("expected_slots"),
        # 从真跑采集到的工具调用 args 还原扁平槽位（跨工具合并/哨兵跳过/last-write-wins）。
        # 真跑失败时 actual_tools 为 None → 还原也为 None → 该用例槽位指标标 N/A，不伪造。
        actual_slots=_slots_from_tool_calls(actual_tools),
        # 任务成功率（change evals-task-success-rate）：期望业务终态 + 实际工具执行成败。
        expected_outcome=case.get("expected_outcome"),
        actual_tool_outcomes=actual_tool_outcomes,
        latency_s=latency,
        judge_passed=judge_passed,  # 回复质量裁决（改造 4）；未开 --judge 时 None→N/A
    )


async def _run_once(cases, llm, full_registry, subagents, capture_fn,
                    judge_fn=None, capture_multiturn_fn=None, concurrency: int = DEFAULT_CONCURRENCY):
    """跑一遍全部用例，返回填好的 ``EvalResult`` 列表（多采样时被调用 N 次）。

    单条逻辑在 ``_run_case``；本函数只负责**调度**，故 N=1 与 N>1、串行与并发
    都走同一条单条路径，口径完全一致。

    并发（change evals-concurrent-runner）：用例之间无共享可变状态（每条一个独立
    ``Tracer`` + ``InMemoryExporter`` 沙盒、``AgentLoop`` 无状态），串行只是历史实现方式。
    这里用 ``asyncio.gather`` + ``Semaphore`` 受限并发：

    - **保序**：``gather`` 按传入顺序返回结果——下游 ``_split_results(cases, results)`` 靠
      zip 同序同长拆 dev/held-out，顺序错乱会把结果张冠李戴，故这是硬约束。
    - **限流**：信号量把在途用例数压到 ``concurrency``；每条用例内部还会派生子 Agent，
      实际在途请求是并发数的数倍，故默认值取保守的 5（见 design D2）。
    - **失败隔离**：异常在 ``_run_case`` 内部就被吞成 N/A，不冒泡到 ``gather``，
      故一条失败不会取消其它在途用例（不用 ``return_exceptions``——那会让异常静默变成
      结果里的异常对象，反而更难查）。
    - ``concurrency <= 1`` 走**串行路径**：不是"信号量=1 的并发"，而是真正的逐条 await，
      作为排障与对照的基准路径，行为与并发化之前等价。
    """
    if concurrency <= 1:  # 串行基准路径（--concurrency 1）：与并发化之前逐条等价
        results = []
        for case in cases:
            results.append(await _run_case(case, llm, full_registry, subagents, capture_fn,
                                           judge_fn, capture_multiturn_fn))
        return results

    sem = asyncio.Semaphore(concurrency)

    async def _guarded(case):
        # async with sem：拿到许可才开跑，出作用域自动释放 → 在途数恒 ≤ concurrency。
        async with sem:
            return await _run_case(case, llm, full_registry, subagents, capture_fn,
                                   judge_fn, capture_multiturn_fn)

    # gather 保序返回（与传入的协程顺序一致，非完成先后），满足上面的「保序」硬约束。
    return list(await asyncio.gather(*(_guarded(c) for c in cases)))


# 模块级占位：真正的 EvalResult 在 run_baseline 内按需 import 后赋给它（避免无 key 路径触碰重依赖）。
_EvalResult = None
_slots_from_tool_calls = None  # 同上：run_baseline 内按需 import 后赋给它


async def run_baseline(
    cases: list[dict],
    samples: int = 1,
    judge: bool = False,
    *,
    gate: bool = False,
    update_baseline: bool = False,
    baseline_path: Path | None = None,
    tolerance: float = 0.30,  # 与 CLI --tolerance 默认值一致（实测半宽校准，见模块 docstring）
    concurrency: int = DEFAULT_CONCURRENCY,  # 用例并发度；1=串行基准路径
) -> int:
    """端到端真跑全部用例, 输出多指标报告。返回进程退出码。

    ``samples<=1``：单次跑，输出多指标报告 + 判错清单 + 按类目视图（与既有一致）。
    ``samples>1``（改造 3）：整套用例独立重跑 N 次，对每个聚合指标输出 ``mean ± 95% t-CI``。
    ``judge=True``（改造 4）：对每条 agent 最终回复跑 LLM-judge，产出回复质量通过率
    （judge 未与人工校准前报告标「未校准」）。
    ``update_baseline``/``gate``（改造 6）：跑完后把结果落盘为基线，或比对基线对回归非零退出。
    """
    # 这些 import 放在函数内（而非文件顶部）：只有「确认要真跑」时才加载重依赖，
    # 也让无 key 的纯清单路径（main 里的 print_cases）不必触碰 provider/分类器。
    from config.model_provider import create_chat_model
    from evals.metrics import (
        EvalResult,
        build_report,
        format_report,
        aggregate_runs,
        format_multisample_report,
        report_to_baseline,
        aggregated_to_baseline,
        compare_to_baseline,
        format_gate_report,
        slots_from_tool_calls,
        validate_gated_metrics,
    )
    from evals.agent_capture import run_and_capture, run_and_capture_multiturn
    from evals.judge import judge_response
    from domains import build_subagent_registry, build_tool_registry, load_domain

    global _EvalResult, _slots_from_tool_calls
    _EvalResult = EvalResult  # 供 _run_once 构造（避免它再触发一次重 import）
    # 槽位键映射随域声明，故这里绑定成 partial 再交给 _run_once——沿用既有「模块级占位」
    # 的形状，不必把映射一路穿过 _run_once/_run_case 的签名。空映射=本域不度量，
    # slots_from_tool_calls 内部会直接返回 None（指标恒 N/A）。
    _slots_from_tool_calls = partial(
        slots_from_tool_calls, slot_key_map=_EVAL_PROFILE.slot_key_map
    )

    try:
        llm = create_chat_model(temperature=0)  # temperature=0：贴生产 + 量残余抖动（改造 3）；judge 同用
        # 端到端真跑所需：全量工具 + 子 Agent 注册中心（每条用例现场拼带 tracer 的主 loop）。
        _domain = load_domain()
        full_registry = build_tool_registry(_domain)
        subagents = build_subagent_registry(_domain)
    except Exception as exc:  # 配置错误(如不支持的 provider): 报告而非崩溃
        print(f"[ERROR] 创建模型/工具失败: {exc}", file=sys.stderr)
        return 2

    # 并发口径如实标注（change evals-concurrent-runner D4）：并发下每条延迟含资源竞争，
    # 不做任何「扣除竞争」的补偿估算（无法诚实计算）。延迟不在门禁集，故不影响回归判定。
    if concurrency > 1:
        print(f"[提示] 用例并发度 ={concurrency}；端到端延迟含并发资源竞争，"
              f"**不可**与串行（--concurrency 1）跑出的历史数字直接比较。"
              f"比率型指标不应受并发影响（若有系统性偏移属实现缺陷）。", file=sys.stderr)

    judge_fn = judge_response if judge else None  # 改造 4：开启时对回复做质量裁决
    if judge:
        print("[提示] 已开启 LLM-judge 评回复质量；judge 与 agent 同模型，未经人工校准 → "
              "报告将标「未校准」，结果仅供参考（自我偏好等偏差未验证）。", file=sys.stderr)

    baseline_path = baseline_path or BASELINE_FILE

    def _finish(baseline_dict: dict, current_view: dict, known_names: set[str]) -> int:
        """改造 6 收尾：按 --update-baseline / --gate 写或比对基线，返回退出码。

        ``current_view``：``{指标名: (value, is_latency)}``，只含非 N/A 指标。
        ``known_names``：本次报告产出的**全部**指标名（含 N/A 项），供门禁声明的语义校验。
        既不开门禁也不写基线时返回 0（默认行为不变）。
        """
        if update_baseline:
            baseline_path.write_text(
                json.dumps(baseline_dict, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"[基线] 已写入 {baseline_path}"
                  f"（{len(baseline_dict['metrics'])} 个非 N/A 指标，samples={baseline_dict['meta']['samples']}）")
            return 0
        if gate:
            if not baseline_path.exists():
                print(f"[ERROR] --gate 需要基线文件，但 {baseline_path} 不存在；"
                      f"请先跑 `--update-baseline` 建立基线。", file=sys.stderr)
                return 1  # 1 = 文件缺失
            gated = _EVAL_PROFILE.gated_metrics
            try:
                # 声明里的名字拼错/声明了不准守的指标，在这里炸而不是静默少守一项。
                validate_gated_metrics(gated, known_names)
            except ValueError as exc:
                print(f"[ERROR] 域 {_DOMAIN.name!r} 的门禁声明非法: {exc}", file=sys.stderr)
                return 2  # 2 = 用例/配置错误
            print(f"[门禁] 域 {_DOMAIN.name!r} 声明被守指标：{', '.join(gated)}")
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            gate_report = compare_to_baseline(current_view, baseline, tolerance, gated=gated)
            print(format_gate_report(gate_report))
            return 0 if gate_report.passed else 3  # 3 = 检测到回归
        return 0

    # 端到端延迟是唯一的延迟型指标（与 metrics 内部口径一致）。
    _LATENCY = "端到端延迟"

    # held-out 是留出集：MUST NOT 参与调优/门禁。若本次评估集合不含 dev（--heldout-only）
    # 却又要求写基线/守门禁，属矛盾请求——main() 已提前拦截，这里防御性兜底（如被直接调用）。
    n_dev = sum(1 for c in cases if c["split"] == "dev")
    if (update_baseline or gate) and n_dev == 0:
        print(
            "[ERROR] 当前评估集合不含 dev 子集（--heldout-only 与 --update-baseline/--gate 不可同用）。",
            file=sys.stderr,
        )
        return 2

    def _print_heldout_section(heldout_results: list, label: str) -> None:
        """held-out 子集单独一节：明确标注不参与门禁/基线（分集呈现，§2.3）。"""
        if not heldout_results:
            return
        print(f"\n{'─' * 60}")
        print(f"[held-out 子集 | 不参与门禁/基线] {label}")

    # ── 单次跑（默认，向后兼容）：报告不含 CI 列 ──────────────────────────────
    if samples <= 1:
        results = await _run_once(cases, llm, full_registry, subagents, run_and_capture,
                                  judge_fn, run_and_capture_multiturn, concurrency=concurrency)
        dev_results, heldout_results = _split_results(cases, results)

        rep = build_report(dev_results, measures_slots=_EVAL_PROFILE.measures_slots)
        if dev_results:
            print(format_report(rep))
        if heldout_results:
            heldout_rep = build_report(heldout_results, measures_slots=_EVAL_PROFILE.measures_slots)
            _print_heldout_section(heldout_results, f"用例数: {len(heldout_results)}")
            print(format_report(heldout_rep))

        if not dev_results:  # 纯 --heldout-only 且未要求基线/门禁：无 dev 侧收尾，直接返回
            return 0
        current_view = {
            m.name: (m.value, m.name == _LATENCY)
            for m in rep["metrics"] if not m.na and m.value is not None
        }
        baseline_dict = report_to_baseline(rep, total_cases=len(dev_results), samples=1)
        return _finish(baseline_dict, current_view, {m.name for m in rep["metrics"]})

    # ── 多采样（改造 3）：整套重跑 N 次 → 聚合 mean ± t-CI ────────────────────
    dev_reports = []
    heldout_reports = []
    n_heldout = len(cases) - n_dev
    for i in range(samples):
        print(f"[采样 {i + 1}/{samples}] 跑整套用例…", file=sys.stderr)
        results = await _run_once(cases, llm, full_registry, subagents, run_and_capture,
                                  judge_fn, run_and_capture_multiturn, concurrency=concurrency)
        dev_results, heldout_results = _split_results(cases, results)
        dev_reports.append(build_report(dev_results, measures_slots=_EVAL_PROFILE.measures_slots))  # 每次跑的聚合指标快照（dev 侧）
        if heldout_results:
            heldout_reports.append(build_report(heldout_results, measures_slots=_EVAL_PROFILE.measures_slots))
    # aggregate_runs/format_multisample_report 是纯函数（吃 N 份报告 → mean±CI），与采样循环解耦。
    aggregated = aggregate_runs(dev_reports) if n_dev else []
    if n_dev:
        print(format_multisample_report(aggregated, samples, n_dev))
    if heldout_reports:
        heldout_aggregated = aggregate_runs(heldout_reports)
        _print_heldout_section(heldout_reports, f"用例数: {n_heldout}")
        print(format_multisample_report(heldout_aggregated, samples, n_heldout))

    if not n_dev:  # 纯 --heldout-only 且未要求基线/门禁
        return 0
    current_view = {
        a.name: (a.mean, a.is_latency)
        for a in aggregated if not a.na and a.mean is not None
    }
    baseline_dict = aggregated_to_baseline(aggregated, total_cases=n_dev, samples=samples)
    # 0/1/2/3 据门禁；无门禁则 0
    return _finish(baseline_dict, current_view, {a.name for a in aggregated})


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
    parser.add_argument(
        "--update-baseline", action="store_true",
        help="把本次跑分落盘为基线(改造 6)；建议配 --samples 3 取稳定均值。与 --gate 互斥",
    )
    parser.add_argument(
        "--gate", action="store_true",
        help="跑完比对基线(改造 6)；被守指标低于基线−容差则以退出码 3 结束。与 --update-baseline 互斥",
    )
    parser.add_argument(
        "--baseline", type=Path, default=BASELINE_FILE,
        help=f"基线文件路径(改造 6)；默认 {BASELINE_FILE.name}(与本脚本同目录)",
    )
    parser.add_argument(
        "--tolerance", type=float, default=0.30,
        help="门禁容差(改造 6)；比率即百分点(0.30=30pp)，经实测半宽校准吸收 LLM 抖动；默认 0.30",
    )
    parser.add_argument(
        "--concurrency", type=int, default=DEFAULT_CONCURRENCY,
        help=f"用例并发度(change evals-concurrent-runner)；默认 {DEFAULT_CONCURRENCY}。"
             "1=串行基准路径(与并发化前等价，排障/对照用)。并发下延迟含资源竞争，"
             "不可与串行历史数字直接比；比率型指标不应受影响",
    )
    parser.add_argument(
        "--include-heldout", action="store_true",
        help="连同 held-out 子集一起评估(change evals-dataset-scaleup-heldout)；"
             "结果分集呈现，MUST NOT 混入 dev 基线；与 --heldout-only 互斥",
    )
    parser.add_argument(
        "--heldout-only", action="store_true",
        help="只评估 held-out 子集；held-out 是过拟合体检的留出集，不参与调优/门禁，"
             "故不可与 --update-baseline/--gate 同用；与 --include-heldout 互斥",
    )
    args = parser.parse_args()

    # --gate 与 --update-baseline 互斥：一次跑要么定基线要么守基线，语义不混。
    if args.gate and args.update_baseline:
        print("[ERROR] --gate 与 --update-baseline 互斥，不能同时指定。", file=sys.stderr)
        return 2  # 2 = 用例/配置错误

    if args.concurrency < 1:  # 0/负数无意义；不静默纠正为 1，坏参数要报出来
        print(f"[ERROR] --concurrency 必须 ≥ 1（收到 {args.concurrency}）。", file=sys.stderr)
        return 2

    if args.include_heldout and args.heldout_only:
        print("[ERROR] --include-heldout 与 --heldout-only 互斥，不能同时指定。", file=sys.stderr)
        return 2

    # held-out 是留出集，MUST NOT 参与调优/门禁；--heldout-only 排除了 dev，
    # 与「基线/门禁恒基于 dev」矛盾，故禁止同用（而非静默地对空 dev 集合定基线）。
    if args.heldout_only and (args.gate or args.update_baseline):
        print(
            "[ERROR] --heldout-only 不含 dev 子集，不能与 --gate/--update-baseline 同用"
            "（基线/门禁恒基于 dev）。",
            file=sys.stderr,
        )
        return 2

    # --gate 早检基线存在：缺基线就别白跑一整轮（比对在跑完后才发生）。
    if args.gate and not args.baseline.exists():
        print(f"[ERROR] --gate 需要基线文件，但 {args.baseline} 不存在；"
              f"请先跑 `--update-baseline` 建立基线。", file=sys.stderr)
        return 1  # 1 = 文件缺失

    if not CASES_FILE.exists():
        print(f"[ERROR] 找不到用例文件: {CASES_FILE}", file=sys.stderr)
        return 1  # 1 = 环境/文件缺失

    cases = load_cases(CASES_FILE)
    cases = _filter_by_split(
        cases, include_heldout=args.include_heldout, heldout_only=args.heldout_only
    )
    if args.limit is not None:
        cases = cases[: args.limit]  # 冒烟模式：只截前 N 条快速验证流程通不通(在切分过滤之后)
    n_dev = sum(1 for c in cases if c["split"] == "dev")
    n_heldout = sum(1 for c in cases if c["split"] == "held-out")
    print(f"已加载 {len(cases)} 条评估用例 ({CASES_FILE.name})；dev={n_dev} held-out={n_heldout}")

    # ★ 优雅降级：没配 key 就「不报错崩溃」，而是退而只打印用例清单 + 怎么配的提示。
    #   这样没 key 的人也能看到评估集长啥样，且 return 2 让 CI 能区分「真跑过」与「跳过了」。
    if not _has_api_key():
        print(
            "\n[提示] 未检测到 API key(MODEL_PROVIDER 对应的 *_API_KEY 未配置)。\n"
            "       无法产出多指标报告; 以下仅为用例清单。\n"
            "       在 .env 配好后重跑: uv run python evals/run_evals.py",
            file=sys.stderr,
        )
        print_cases(cases)
        return 2  # 2 = 优雅降级（没真跑分类器）

    # 有 key：进入真正的异步评估。asyncio.run 负责建/关事件循环跑这个协程。
    return asyncio.run(run_baseline(
        cases, samples=args.samples, judge=args.judge,
        gate=args.gate, update_baseline=args.update_baseline,
        baseline_path=args.baseline, tolerance=args.tolerance,
        concurrency=args.concurrency,
    ))


if __name__ == "__main__":
    # 作为脚本直接运行时的入口；把 main 的返回码交给 SystemExit → 即进程退出码（供 shell/CI 判定）。
    raise SystemExit(main())
