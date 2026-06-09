"""默认 SpanExporter：把 span 经既有结构化日志以单行 JSON 输出（Phase 6）。

复用 ``config/logging_setup.py`` 的 JSON 日志风格（``ensure_ascii=False`` 保留中文），
零额外依赖——**绝不 import OpenTelemetry**（design.md：默认路径不依赖 OTel）。
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from harness.observability.span import Span

__all__ = ["LoggingSpanExporter"]

_DEFAULT_LOGGER = "harness.observability"


class LoggingSpanExporter:
    """把每个结束的 span 序列化为单行 JSON，经标准 logging 输出。"""

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger(_DEFAULT_LOGGER)

    def export(self, span: Span) -> None:
        payload = {"event": "span", **span.to_dict()}
        # message 即整条 span JSON；JsonFormatter 会再包一层 envelope，但单独使用
        # 标准 formatter 时这行本身也是可读的结构化记录。
        self._logger.info(json.dumps(payload, ensure_ascii=False, default=str))
