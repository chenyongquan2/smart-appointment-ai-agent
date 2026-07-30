"""任务执行层：Channel 与 Agent 之间的任务式接口（change: feishu-channel-integration）。

单向依赖：``channels/`` → ``executor/`` → ``harness/``。executor MUST NOT 反向依赖任何
Channel 实现，这正是「换掉飞书换成钉钉，Agent 层零改动」的分层判据落点。
"""

from executor.local import (
    BUSY_REPLY,
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_MAX_QUEUE_PER_SESSION,
    DEFAULT_WALL_CLOCK_TIMEOUT,
    FAILED_REPLY,
    TIMEOUT_REPLY,
    SessionBusy,
    TaskExecutor,
)
from executor.task import Task, TaskResult, TaskStatus

__all__ = [
    "Task",
    "TaskResult",
    "TaskStatus",
    "TaskExecutor",
    "SessionBusy",
    "BUSY_REPLY",
    "FAILED_REPLY",
    "TIMEOUT_REPLY",
    "DEFAULT_MAX_CONCURRENCY",
    "DEFAULT_MAX_QUEUE_PER_SESSION",
    "DEFAULT_WALL_CLOCK_TIMEOUT",
]
