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
        # 默认取项目约定的命名 logger；调用方也可注入自己的，便于按需配 handler/级别。
        self._logger = logger or logging.getLogger(_DEFAULT_LOGGER)

    def export(self, span: Span) -> None:
        # to_dict() 已把 span 拍平成可序列化字典；再加个 "event": "span" 标记，
        # 方便后续在日志流里按字段筛出这类记录。**展开是为了把标记和内容并到同一层。
        payload = {"event": "span", **span.to_dict()}
        # message 即整条 span JSON；JsonFormatter 会再包一层 envelope，但单独使用
        # 标准 formatter 时这行本身也是可读的结构化记录。
        # ensure_ascii=False：保留中文原文（不转成 \uXXXX 转义），日志直接可读。
        # default=str：遇到 json 不认识的类型时兜底 str() 化，绝不让序列化抛错
        #              （呼应 export「不得抛出」的契约——可观测不能拖垮主流程）。
        self._logger.info(json.dumps(payload, ensure_ascii=False, default=str))
