"""FileSpanExporter 的离线确定性单测（改造 7 · 在线评估闭环）。

验证：① span 以单行 JSON 追加落盘、逐行 json.loads 可还原回 to_dict() 结构；
② 写盘失败（注入会抛的伪文件）时 export 不抛、仅 warning。全程不触网。
"""

import json

from harness.observability.file_exporter import FileSpanExporter
from harness.observability.span import Span, SpanEvent


def _span(trace_id: str, span_id: str, name: str, events=None) -> Span:
    s = Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_id=None,
        name=name,
        start=1.0,
        end=2.0,
        attributes={"session_id": "s-1"},
        events=list(events or []),
    )
    return s


def test_export_appends_one_json_line_per_span(tmp_path):
    path = tmp_path / "traces" / "trace-x.jsonl"  # 目录尚不存在：构造时应自动建
    exporter = FileSpanExporter(path=path)

    root = _span("t-1", "sp-1", "agent_loop.run")
    step = _span(
        "t-1",
        "sp-2",
        "step",
        events=[SpanEvent("tool_call", {"name": "find_technician", "args": {"项目": "推拿"}})],
    )
    step.parent_id = "sp-1"
    exporter.export(root)
    exporter.export(step)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    rec0 = json.loads(lines[0])
    assert rec0["event"] == "span"
    # 去掉 event 标记后应与 to_dict() 完全一致。
    rec0.pop("event")
    assert rec0 == root.to_dict()

    rec1 = json.loads(lines[1])
    assert rec1["parent_id"] == "sp-1"
    # 中文不转义（ensure_ascii=False）：原文可读。
    assert "推拿" in lines[1]


def test_export_swallows_write_failure(tmp_path, caplog):
    exporter = FileSpanExporter(path=tmp_path / "t.jsonl")

    class _BoomPath:
        def open(self, *a, **k):
            raise OSError("disk full")

    exporter._path = _BoomPath()  # type: ignore[assignment]

    # 不得抛：可观测附属能力绝不拖垮主流程。
    exporter.export(_span("t-2", "sp-9", "agent_loop.run"))  # 若抛异常则测试失败
