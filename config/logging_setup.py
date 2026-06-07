"""集中式结构化(JSON)日志配置。

Phase 0 的"最简 trace":让全应用日志以单行 JSON 输出(有级别、可过滤、可采集),
替换散落的 `print`。由 `app.py` 启动时调用 `setup_logging()`。

非目标:这里只做"结构化输出",不实现全链路 tracer / 每步 input-output 记录
(那属于 Phase 6 的可观测性)。
"""

import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    """把日志记录格式化为单行 JSON。

    字段:timestamp / level / logger / message;有异常时附 `exc_info` 文本。
    `ensure_ascii=False` 保留中文可读(配合 app.py 的 UTF-8 stdout 设置)。
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> None:
    """配置 root logger 以 JSON 格式输出到 stdout。

    幂等:重复调用会先清掉已有 handler,避免重复输出。

    Windows 中文环境 stdout 默认 gbk,无法编码中文/emoji 日志;尽力将其
    重配为 UTF-8(与 app.py 一致),使本模块单独使用时也不崩。
    """
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
