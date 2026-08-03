"""轻量 Span 模型（Phase 6 可观测层）。

不依赖任何第三方库——一次请求的每个 span 在内部就是这个 dataclass：
``trace_id`` 串联同一请求、``parent_id`` 指向上一层（root span 为 ``None``），
``events`` 顺序记录 thought / tool_call / observation 等，``attributes`` 挂
session_id / token 近似 / 工具名 等可检索字段。latency 由开始/结束时刻计算。

设计要点（design.md D1）：span 父子关系由我们显式持有（``parent_id``），不依赖
OpenTelemetry 的隐式 context 传播，故在手写 async 循环里也不会断树。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = ["Span", "SpanEvent"]


@dataclass
class SpanEvent:
    """span 上的一个时点事件，如 thought / tool_call / observation。"""

    kind: str  # 事件类型标签；约定值见 tracer 的 add_thought/add_tool_call/add_observation
    payload: dict[str, Any]  # 该事件的内容，形状随 kind 而变（如 {"text": ...} / {"name", "args"}）


@dataclass
class Span:
    """一次 trace 中的单个跨度。

    Attributes:
        trace_id: 同一请求内所有 span 共享，用于回放检索。
        span_id: 本 span 唯一标识。
        parent_id: 父 span 的 ``span_id``；root span 为 ``None``。
        name: span 名称（如 ``agent_loop.run`` / ``step``）。
        start: 开始时刻（来自注入的 monotonic clock，仅用于算 latency）。
        end: 结束时刻；``None`` 表示尚未结束。
        started_at: 开始时刻的**墙钟**读数（UTC ISO8601 串）；``None`` 表示未记录
            （如手工构造的 span、或从旧格式 trace 文件还原的 span）。
        attributes: 可检索属性（session_id / user_id / token 近似 / 工具名 / 参数 等）。
        events: 顺序事件列表（thought / tool_call / observation ...）。

    ⚠ **两套时间各司其职，绝不互相替代**（change ``fix-trace-triage-blindspots`` D4）：
    ``start``/``end`` 是单调 clock（``perf_counter``），只用来算 latency——系统时间回拨
    时它仍单调，故 latency 不会算出负数；``started_at`` 是绝对时间，只用来回答「这条
    trace 是什么时候的」（按日期切窗、与 IM 上的消息对时间）。把 ``start`` 改成墙钟会
    在时间回拨时产生负耗时，故必须并存而非合并。
    """

    trace_id: str  # 同一请求内全部 span 共享同一个值（串联整条 trace 的关键）
    span_id: str  # 本 span 唯一 id；会被「子 span」抄进它的 parent_id
    parent_id: Optional[str]  # 父的 span_id；root 为 None ←—— 父子树就靠这一字段显式连起来
    name: str
    start: float  # 开始时刻（注入的单调 clock 读数，非墙钟时间，只用来算差值）
    end: Optional[float] = None  # 结束时刻；None = 还没结束
    # 墙钟起始时刻（UTC ISO8601 串）。与 start 并存：start 算耗时、started_at 定位时间点。
    # 存字符串而非 epoch float：JSONL 要人能直接看、能 grep；且「UTC + 同一格式」时
    # 字典序即时间序，triage 排序与 --since 比较都不必先解析。
    started_at: Optional[str] = None
    # 下面两个用 default_factory：dataclass 默认值若直接写 {} / [] 会被「所有实例共享」
    # 同一个对象（Python 可变默认值的经典坑）；用工厂函数保证每个 Span 各得一份新容器。
    attributes: dict[str, Any] = field(default_factory=dict)  # 可检索标量字段（session_id/tokens/tool_name…）
    events: list[SpanEvent] = field(default_factory=list)  # 按发生顺序排列的事件流

    @property
    def latency(self) -> Optional[float]:
        """span 耗时（秒）；未结束时为 ``None``。"""
        # 用 property 而非存字段：latency 永远是 end-start 的派生值，按需算，免得
        # end 一变还要记得同步更新另一个字段（单一真相源）。
        if self.end is None:
            return None  # 还没 end_span，算不出耗时
        return self.end - self.start  # 两个 clock 读数相减 → 秒数

    def to_dict(self) -> dict[str, Any]:
        """规整为可序列化字典（供 JSON 日志 exporter 与断言使用）。"""
        # 刻意「拍平」成纯 dict/list/标量：这样能直接喂给 json.dumps，也方便测试里
        # 用普通字典断言，不必依赖 dataclass 比较。
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "latency": self.latency,  # 注意：导出的是「算好的耗时」，不是 start/end 原值
            # 墙钟起始时刻：单调 clock 的 start/end 是进程内读数、跨进程无意义，故不导出；
            # 这个才是「什么时候发生的」的唯一可用来源（triage 按日期切窗靠它）。
            "started_at": self.started_at,
            "attributes": dict(self.attributes),  # 拷一份，防外部拿到引用后改坏内部状态
            # 每个 SpanEvent 也展开成普通 dict（嵌套对象同样拍平）。
            "events": [{"kind": e.kind, "payload": e.payload} for e in self.events],
        }
