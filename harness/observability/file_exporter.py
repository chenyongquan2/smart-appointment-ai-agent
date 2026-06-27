"""落盘型 SpanExporter：把 span 以单行 JSON 追加写入文件（改造 7 · 在线评估闭环）。

与 ``LoggingSpanExporter`` 的分工：后者把 span 经标准 logging 输出（受 handler/格式器
影响、不保证一个稳定可逐行 ``json.loads`` 的文件）；本 exporter 直接把每个结束的 span
追加写进一个确定的 JSONL 文件，**作为 triage 的可检索 trace 源**（design.md D1）。

设计要点：
- **单行 JSON**：``{"event":"span", **span.to_dict()}`` + ``ensure_ascii=False``（保留中文）
  + ``default=str``（遇不可序列化类型兜底，绝不让序列化抛错）——与 ``logging_exporter`` 同口径。
- **不得抛**（design.md D3）：``export`` 内吞一切 IO/序列化异常，失败仅 warning，绝不把
  异常抛回主循环（呼应 ``exporter.py`` 协议「同步、不得抛出以免影响主流程」）。可观测是
  附属能力，不能因写盘失败拖垮用户请求。
- **零额外依赖**：绝不 import OpenTelemetry（默认路径不依赖 OTel）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Union

from harness.observability.span import Span

__all__ = ["FileSpanExporter", "DEFAULT_TRACE_DIR"]

# 默认 trace 落盘目录：运行期产物，已在 .gitignore 忽略（与 data/、logs/ 同类）。
DEFAULT_TRACE_DIR = Path(__file__).resolve().parents[2] / "evals" / "traces"

_DEFAULT_LOGGER = "harness.observability"


class FileSpanExporter:
    """把每个结束的 span 以单行 JSON 追加写入一个 JSONL 文件。

    Args:
        path: 目标 JSONL 文件路径。缺省时在 ``DEFAULT_TRACE_DIR`` 下用 ``run_id`` 命名
            （``trace-<run_id>.jsonl``）；``run_id`` 缺省取一个固定占位名（调用方通常
            按启动时刻/uuid 传入以区分多次运行——本 exporter 不调禁用的时间/随机 API）。
        logger: 失败 warning 用的 logger；缺省取项目约定的命名 logger。
    """

    def __init__(
        self,
        path: Optional[Union[str, Path]] = None,
        run_id: str = "default",
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._path = Path(path) if path is not None else DEFAULT_TRACE_DIR / f"trace-{run_id}.jsonl"
        self._logger = logger or logging.getLogger(_DEFAULT_LOGGER)
        # 目录可能尚不存在：建目录这步也不得抛（同属可观测附属逻辑）。
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._logger.warning("FileSpanExporter 无法创建 trace 目录 %s", self._path.parent, exc_info=True)

    @property
    def path(self) -> Path:
        """当前 exporter 写入的 JSONL 文件路径（供调用方/测试定位）。"""
        return self._path

    def export(self, span: Span) -> None:
        """把一个已结束的 span 追加写入 JSONL 文件。失败仅 warning，绝不抛出。"""
        try:
            # to_dict() 已把 span 拍平为可序列化结构；加 "event":"span" 标记便于按字段筛。
            line = json.dumps(
                {"event": "span", **span.to_dict()},
                ensure_ascii=False,
                default=str,
            )
            # 追加模式：同一次运行的多个 span 依次落到同一文件，逐行 json.loads 可还原。
            with self._path.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")
        except Exception:  # noqa: BLE001 —— 故意吞「全部」异常：可观测不得拖垮主流程
            # 宁可丢一条 trace，也绝不把写盘异常抛回 AgentLoop 的关键路径。
            self._logger.warning("FileSpanExporter 写盘失败，已丢弃该 span", exc_info=True)
