"""评估集运行器（Phase 0 骨架）。

用法:
    uv run python evals/run_evals.py

当前为骨架: 只加载并校验用例、打印占位清单。
TODO(Phase 0/1): 接入真实的意图分类 / 工具调用, 逐条比对 expected, 输出准确率基线。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Windows 中文环境控制台默认 gbk，无法编码中文/emoji，统一转为 UTF-8（与 app.py 一致）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

CASES_FILE = Path(__file__).parent / "cases.jsonl"


def load_cases(path: Path) -> list[dict]:
    """读取 jsonl 用例; 跳过空行与 // 注释行。"""
    cases: list[dict] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"[ERROR] 第 {lineno} 行 JSON 解析失败: {exc}", file=sys.stderr)
            raise
    return cases


def main() -> int:
    if not CASES_FILE.exists():
        print(f"[ERROR] 找不到用例文件: {CASES_FILE}", file=sys.stderr)
        return 1

    cases = load_cases(CASES_FILE)
    print(f"已加载 {len(cases)} 条评估用例 ({CASES_FILE.name})\n")

    # TODO(Phase 0/1): 对每条 case 调用真实分类/agent, 与 expected_intent / expected_tools 比对。
    # 目前仅打印清单, 作为基线脚手架。
    for case in cases:
        intent = case.get("expected_intent", "?")
        tools = ", ".join(case.get("expected_tools", [])) or "-"
        text = case.get("input", "")
        print(f"  [{intent:12}] {text[:40]:<40}  tools=[{tools}]")

    print("\n(骨架模式: 尚未接入真实 agent。接入后此处输出准确率基线。)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
