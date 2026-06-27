"""在线评估闭环的 triage：从落盘 trace 半自动甄别坏 case → 人审标注 → 回灌 cases.jsonl。

改造 7（agent-eval-fieldguide.md §13）。整条闭环：
  生产对话 → FileSpanExporter 落 evals/traces/*.jsonl
           → 本模块 scan：按 trace_id 分组、用客观信号甄别「疑似坏」候选、还原标注草稿
           → 人工编辑草稿（填 expected_*，真值绝不自动伪造）
           → 本模块 append：去重后追加进 evals/cases.jsonl（带 source=online）+ 提醒重定基线

设计要点（design.md）：
- **纯函数核心**（`load_trace_spans` / `triage_traces` / `append_cases`）：不触网、不调 LLM，可离线确定性单测。
- **信号判定复用 harness**（`detect_bad_signals`）：与采样 exporter 同一套口径，且不反向依赖 evals。
- **按 trace_id 分组**：C-lite 下子 Agent 各自开 root span（trace_id 不同），故一条 trace_id = 一个候选；
  子 Agent 内部失败会作为「以被委派 task 为 input」的独立候选出现——诚实边界见 README，跨 loop 关联属后续工作。
- **真值人审**：scan 只产「草稿」（expected_* 留空待填），绝不自动判真值或自动改 cases.jsonl。
- **回灌不自动重定基线**：append 完只打印提醒，baseline.json 不动（基线变更走人审，不绕过改造 6 门禁）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

from evals.trace_collect import collect_tool_calls
from harness.observability.span import Span, SpanEvent
from harness.observability.trace_signals import detect_bad_signals

# 与 evals/cases.jsonl 同构的「真值」字段白名单——append 只写这些键，绝不把草稿的辅助字段写进用例集。
CANONICAL_KEYS = (
    "input",
    "expected_intent",
    "expected_tools",
    "expected_tool_args",
    "expected_slots",
    "source",
)

_CASES_FILE = Path(__file__).parent / "cases.jsonl"
_TRACES_DIR = Path(__file__).parent / "traces"
_ONLINE_SECTION_HEADER = "// --- online 回灌 (改造 7) ---"


# ════════════════════════════════════════════════════════════════════════════
# trace 解析（纯函数）
# ════════════════════════════════════════════════════════════════════════════
def load_trace_spans(path: Path) -> list[Span]:
    """从一个 trace JSONL 文件还原 Span 列表。

    文件每行是 FileSpanExporter 落的 ``{"event":"span", **span.to_dict()}``。``to_dict`` 只存
    ``latency`` 不存 start/end，故这里用**文件行序**当 synthetic start——同一 tracer 的 span 按完成
    顺序追加，与按 start 排序一致，足够 `detect_bad_signals` / `collect_tool_calls` 的排序用途。
    """
    spans: list[Span] = []
    for idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines()):
        line = raw.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("event") != "span":
            continue
        events = [SpanEvent(kind=e.get("kind", ""), payload=e.get("payload") or {}) for e in rec.get("events", [])]
        spans.append(
            Span(
                trace_id=rec.get("trace_id", ""),
                span_id=rec.get("span_id", ""),
                parent_id=rec.get("parent_id"),
                name=rec.get("name", ""),
                start=float(idx),  # synthetic：文件行序即完成序，可比较即可
                end=float(idx),
                attributes=rec.get("attributes") or {},
                events=events,
            )
        )
    return spans


def _group_by_trace(spans: Iterable[Span]) -> dict[str, list[Span]]:
    groups: dict[str, list[Span]] = {}
    for s in spans:
        groups.setdefault(s.trace_id, []).append(s)
    return groups


def _root_input(group: list[Span]) -> str:
    """取该 trace 组的 root span（parent_id 为 None）的 user_input 属性。"""
    for s in group:
        if s.parent_id is None:
            return str(s.attributes.get("user_input", ""))
    return ""


def _last_thought(group: list[Span]) -> str:
    """best-effort 取最后一步的 thought 文本（终态回复；坏 trace 可能为空/兜底，仅供草稿参考）。"""
    text = ""
    for s in sorted(group, key=lambda s: s.start):
        for e in s.events:
            if e.kind == "thought":
                text = str(e.payload.get("text", ""))
    return text


def triage_traces(spans: Iterable[Span]) -> list[dict[str, Any]]:
    """按 trace_id 分组甄别「疑似坏」，对每个命中信号的组产出一份标注草稿。

    Returns:
        草稿列表（按 trace_id 排序，确定可复现）；每份含观测到的信号/工具/回复，以及**留空待人填**
        的 expected_* 字段。无任何坏信号的 trace 不入选。
    """
    candidates: list[dict[str, Any]] = []
    for trace_id, group in sorted(_group_by_trace(spans).items()):
        signals = detect_bad_signals(group)
        if not signals:
            continue
        observed_tools = [c["name"] for c in collect_tool_calls(group)]
        candidates.append(
            {
                "input": _root_input(group),
                # —— 留空待人审填写（真值绝不自动伪造）——
                "expected_intent": "",
                "expected_tools": [],
                "expected_tool_args": {},
                "expected_slots": {},
                "source": "online",
                # —— 观测元信息（辅助人工判断；append 时按白名单丢弃，不写进 cases.jsonl）——
                "_trace_id": trace_id,
                "_signals": signals,
                "_observed_tools": observed_tools,
                "_observed_reply": _last_thought(group),
            }
        )
    return candidates


# ════════════════════════════════════════════════════════════════════════════
# 回灌 cases.jsonl（纯函数）
# ════════════════════════════════════════════════════════════════════════════
def normalize_input(text: Any) -> str:
    """input 去重规范化：与 metrics._normalize_arg 同口径（strip+lower）再折叠内部空白。"""
    return " ".join(str(text).strip().lower().split())


def load_existing_inputs(cases_path: Path) -> set[str]:
    """读现有 cases.jsonl（跳 // 注释与空行，与 run_evals.load_cases 同口径），返回规范化 input 集合。"""
    inputs: set[str] = set()
    if not cases_path.exists():
        return inputs
    for raw in cases_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError:
            continue  # 现有文件里的坏行不归本流程管（run_evals 会报），这里只为收集 input
        if "input" in case:
            inputs.add(normalize_input(case["input"]))
    return inputs


def _canonical_case(draft: dict[str, Any]) -> dict[str, Any]:
    """从草稿按白名单抽出真值字段；丢弃 _ 前缀辅助字段。缺省补默认值、标 source=online。"""
    case = {k: draft[k] for k in CANONICAL_KEYS if k in draft and not k.startswith("_")}
    case.setdefault("source", "online")
    return case


def append_cases(cases_path: Path, new_cases: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """把人审通过的用例去重后追加进 cases.jsonl。**不自动重定基线**。

    去重口径：规范化 input 既不与现有用例重复、也不与本批已加入的重复。新用例只写 CANONICAL_KEYS、
    带 ``source``，落在 online 分节标题下。

    Returns:
        报告 dict：``{"added": [...], "skipped": [(input, reason), ...]}``。
    """
    existing = load_existing_inputs(cases_path)
    added: list[dict[str, Any]] = []
    skipped: list[tuple[str, str]] = []
    seen_this_batch: set[str] = set()

    for draft in new_cases:
        case = _canonical_case(draft)
        norm = normalize_input(case.get("input", ""))
        if not norm:
            skipped.append((str(case.get("input", "")), "empty-input"))
            continue
        if norm in existing:
            skipped.append((str(case["input"]), "exists"))
            continue
        if norm in seen_this_batch:
            skipped.append((str(case["input"]), "dup-in-batch"))
            continue
        seen_this_batch.add(norm)
        added.append(case)

    if added:
        text = cases_path.read_text(encoding="utf-8") if cases_path.exists() else ""
        chunk = ""
        # 没有 online 分节标题时补一个（仅首次回灌时加）。
        if _ONLINE_SECTION_HEADER not in text:
            chunk += ("\n" if text and not text.endswith("\n") else "") + _ONLINE_SECTION_HEADER + "\n"
        for case in added:
            chunk += json.dumps(case, ensure_ascii=False) + "\n"
        with cases_path.open("a", encoding="utf-8") as fp:
            fp.write(chunk)

    return {"added": added, "skipped": skipped}


# ════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════
_REBASELINE_HINT = (
    "用例集已变更：请人工重定基线 → uv run python evals/run_evals.py --samples 3 --update-baseline\n"
    "（回灌不自动改 baseline.json——基线变更走人审，不绕过改造 6 门禁。）"
)


def _cmd_scan(args: argparse.Namespace) -> int:
    traces_dir = Path(args.traces_dir)
    if not traces_dir.exists():
        print(f"[ERROR] trace 目录不存在: {traces_dir}", file=sys.stderr)
        return 1
    all_spans: list[Span] = []
    files = sorted(traces_dir.glob("*.jsonl"))
    for f in files:
        all_spans.extend(load_trace_spans(f))
    candidates = triage_traces(all_spans)
    out = json.dumps(candidates, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
        print(f"扫描 {len(files)} 个 trace 文件，得 {len(candidates)} 个疑似坏候选 → 草稿已写入 {args.out}")
        print("请人工编辑草稿、填好 expected_*（删去 _ 前缀辅助字段可选），再用 `append --from` 回灌。")
    else:
        print(out)
    return 0


def _cmd_append(args: argparse.Namespace) -> int:
    drafts_path = Path(args.from_file)
    if not drafts_path.exists():
        print(f"[ERROR] 草稿文件不存在: {drafts_path}", file=sys.stderr)
        return 1
    drafts = json.loads(drafts_path.read_text(encoding="utf-8"))
    if not isinstance(drafts, list):
        print("[ERROR] 草稿文件应为 JSON 列表（一组用例）。", file=sys.stderr)
        return 2
    report = append_cases(Path(args.cases), drafts)
    print(f"回灌完成：新增 {len(report['added'])} 条，跳过 {len(report['skipped'])} 条。")
    for inp, reason in report["skipped"]:
        print(f"  跳过[{reason}]: {inp[:48]}")
    if report["added"]:
        print("\n" + _REBASELINE_HINT)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="在线评估闭环 triage（改造 7）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="扫描 trace 目录，甄别疑似坏候选并产出标注草稿")
    p_scan.add_argument("--traces-dir", default=str(_TRACES_DIR), help=f"trace 目录；默认 {_TRACES_DIR}")
    p_scan.add_argument("--out", default=None, help="草稿输出文件（JSON 列表）；缺省打到 stdout")
    p_scan.set_defaults(func=_cmd_scan)

    p_app = sub.add_parser("append", help="把人审通过的草稿去重后回灌进 cases.jsonl")
    p_app.add_argument("--from", dest="from_file", required=True, help="人工编辑后的草稿文件（JSON 列表）")
    p_app.add_argument("--cases", default=str(_CASES_FILE), help=f"目标用例集；默认 {_CASES_FILE}")
    p_app.set_defaults(func=_cmd_append)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
