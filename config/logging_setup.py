"""集中式结构化(JSON)日志配置。

Phase 0 的"最简 trace":让全应用日志以单行 JSON 输出(有级别、可过滤、可采集),
替换散落的 `print`。由 `app.py` 启动时调用 `setup_logging()`。

非目标:这里只做"结构化输出",不实现全链路 tracer / 每步 input-output 记录
(那属于 Phase 6 的可观测性)。
"""

import json
import logging
import sys


# ``LogRecord`` 自带的属性名。凡不在此集合中的，都是调用方经 ``extra={...}`` 传进来的
# 业务字段——它们才是结构化日志真正的价值所在。
# 用「排除已知标准属性」而非「维护一份业务字段白名单」：后者每加一个字段都要改这里，
# 必然会漏，而漏掉的表现是「日志里悄悄少了一个字段」，极难发现。
_STANDARD_RECORD_ATTRS = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "msg", "name", "pathname",
    "process", "processName", "relativeCreated", "stack_info", "thread", "threadName",
    "message",    # getMessage() 的结果，logging 自己会塞
    "taskName",   # Python 3.12+
})


class JsonFormatter(logging.Formatter):
    """把日志记录格式化为单行 JSON。

    字段:timestamp / level / logger / message;有异常时附 `exc_info` 文本;
    经 ``extra={...}`` 传入的业务字段一并平铺输出。
    `ensure_ascii=False` 保留中文可读(配合 app.py 的 UTF-8 stdout 设置)。

    为什么必须输出 ``extra``:调用方写 ``logger.info("已提交任务", extra={"session_id": ...})``
    时,真正有排障价值的是那些字段。此前本 formatter 只取固定四项、把 ``extra`` 全部丢弃,
    于是全应用的结构化字段等于白写——日志看着"结构化",实际只有一句话。
    """

    def format(self, record: logging.LogRecord) -> str:
        # 先放业务字段,再放核心四项:这样核心字段名永远不会被 extra 里的同名键顶掉
        # (logging 自身只保护 message/asctime 等,不保护我们自定的 timestamp/level/logger)。
        payload = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_ATTRS
        }
        payload.update({
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        })
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # default=str:extra 里可能塞了枚举、asyncio.Task 这类不可序列化对象
        # (如 gateway 传的 ack_task)。日志绝不能因为一个字段序列化不了就抛异常——
        # 那会把"记录一次失败"变成"再制造一次失败"。
        return json.dumps(payload, ensure_ascii=False, default=str)


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
