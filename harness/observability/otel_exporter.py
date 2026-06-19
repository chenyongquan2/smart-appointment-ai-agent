"""可选 OpenTelemetry SpanExporter（Phase 6 可观测层）。

把内部 :class:`~harness.observability.span.Span` 映射为 OTel span：root/child 层级
一致、``duration`` 取自内部 latency、``attributes`` 含 token 近似 / 工具名 / 参数。
可对接 OTel ``InMemorySpanExporter`` 在单测中离线断言，全程不触网。

隔离要求（design.md D6）：OpenTelemetry 仅在本模块、且仅当**启用**该 exporter 时
才需要——其 import 在 ``__init__`` 内进行，缺失时抛清晰错误；包的 ``__init__`` 不
导入本模块，故默认 JSON 日志路径不会 import OTel。

子 span 先于父 span 结束（root 最后结束），故按 trace 缓冲，待 root 到达再统一
按"父先于子"的顺序构建 OTel span，从而正确重建父子上下文（不依赖 OTel 隐式 context）。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from harness.observability.span import Span

__all__ = ["OTelSpanExporter"]


class OTelSpanExporter:
    """内部 span → OpenTelemetry span 的 exporter。

    Args:
        otel_tracer: 可选的 OTel ``Tracer``；缺省时取全局 tracer。测试可传入接到
            ``InMemorySpanExporter`` 的 provider 所得 tracer，以离线断言。
    """

    def __init__(self, otel_tracer: Optional[Any] = None) -> None:
        # ★ import 故意放在 __init__ 里、而非模块顶部：opentelemetry 是「可选」依赖，
        #   只有真去 new 这个 exporter 时才需要它。默认 JSON 日志路径压根不碰本类，
        #   所以没装 OTel 的环境也能正常跑（隔离要求，design.md D6）。
        try:
            from opentelemetry import trace
            from opentelemetry.trace import set_span_in_context
        except ImportError as exc:  # pragma: no cover - 仅在缺依赖时触发
            # 缺依赖时抛「清晰可操作」的错误（告诉怎么装），而不是一句 ImportError。
            raise RuntimeError(
                "启用 OTelSpanExporter 需安装 opentelemetry-sdk（uv add opentelemetry-sdk）"
            ) from exc

        # 把导入到的函数/对象「存成实例属性」，后续方法直接用 self.xxx，不必再 import。
        self._set_span_in_context = set_span_in_context
        self._otel_tracer = otel_tracer or trace.get_tracer("harness.observability")
        # ★ 按 trace_id 分桶缓冲：{trace_id: [本 trace 已到达的 span...]}。
        #   为什么要缓冲见下方 export——span 是「子先结束、root 最后结束」乱序到达的。
        self._buffer: dict[str, list[Span]] = {}

    def export(self, span: Span) -> None:
        """缓冲 span；当 root（``parent_id`` 为 None）到达时整条 trace 一次性落地。"""
        # ★ 为什么不能来一个就立刻建 OTel span？因为 end_span 的调用顺序是「子先父后」
        #   （见 agent_loop：step 在 finally 里先 end，root 最后 end）——子到达时父还没
        #   建出来，没法挂上下文。故先按 trace_id 攒着……
        self._buffer.setdefault(span.trace_id, []).append(span)
        if span.parent_id is None:
            # ……直到 root（无父者）到达——此刻整条 trace 的 span 已全部到齐，统一落地。
            self._flush(span.trace_id)

    def _flush(self, trace_id: str) -> None:
        spans = self._buffer.pop(trace_id, [])  # pop：取出并清桶，避免内存泄漏/重复落地
        # 先排序成「父一定在子之前」，下面建 span 时才能保证用到父时它已经建好了。
        ordered = _parents_before_children(spans)

        # ── 第一趟：按序「创建并 start」每个 OTel span，挂好父子上下文 ──
        created: dict[str, Any] = {}  # 内部 span_id → 已建好的 OTel span 对象
        for s in ordered:
            # 用内部 parent_id 查出「已建好的父 OTel span」（root 则没有父）。
            parent_otel = created.get(s.parent_id) if s.parent_id else None
            # ★ 把父显式包成 OTel context 传给子——这是「不依赖 OTel 隐式 context 传播」
            #   的关键：我们自己用持有的 parent_id 重建父子关系，手写 async 循环里也不断树。
            context = self._set_span_in_context(parent_otel) if parent_otel else None
            otel_span = self._otel_tracer.start_span(
                s.name,
                context=context,
                start_time=_to_ns(s.start),  # 用内部记录的开始时刻，对齐时间轴
            )
            self._apply_attributes(otel_span, s)
            created[s.span_id] = otel_span  # 登记，供后续子 span 查父用

        # ── 第二趟：逐个 end ──
        # 结束（end 触发 SimpleSpanProcessor 导出）；end_time 用内部结束时刻，
        # 使 OTel duration == 内部 latency。
        for s in ordered:
            # 极端兜底：万一没记到 end（理论上 end_span 必会记），退用 start，
            # 至少得到 duration=0 的 span，而不是报错。
            end = s.end if s.end is not None else s.start
            created[s.span_id].end(end_time=_to_ns(end))

    def _apply_attributes(self, otel_span: Any, s: Span) -> None:
        # 原始属性中的标量直接搬运（OTel 属性仅接受标量/标量序列）。
        for key, value in s.attributes.items():
            # 显式过滤：只搬标量（str/bool/int/float）。OTel 不接受 dict/嵌套对象，
            # 直接塞会报错，故非标量在这里被悄悄跳过。
            if isinstance(value, (str, bool, int, float)):
                otel_span.set_attribute(key, value)
        # 工具参数（dict）序列化为 JSON 字符串作为属性。
        # 上面那条规则会漏掉「工具参数」——它是 dict，不是标量。所以单独处理：
        # 从事件里捞出 tool_call 的 args，JSON 化成字符串再当属性塞进去。
        for event in s.events:
            if event.kind == "tool_call":
                otel_span.set_attribute(
                    "tool_args",
                    # 同样 ensure_ascii=False 保中文、default=str 兜底防序列化抛错。
                    json.dumps(event.payload.get("args"), ensure_ascii=False, default=str),
                )


def _to_ns(seconds: float) -> int:
    """秒（来自内部单调时钟）→ 纳秒整数（OTel start_time/end_time 口径）。"""
    # OTel 的时间戳要的是「纳秒整数」；我们内部是「秒浮点」，故乘 1e9 再取整换算。
    return int(seconds * 1_000_000_000)


def _parents_before_children(spans: list[Span]) -> list[Span]:
    """稳定拓扑排序：父 span 一定排在其子 span 之前。"""
    # 思路：反复扫描，每轮把「父已经就位（或本身是 root）」的 span 收编进结果，
    #       直到全部收完。保证任何 span 出现时，它的父早已在前面（建 OTel span 才有父可挂）。
    placed: set[str] = set()  # 已就位的 span_id 集合
    ordered: list[Span] = []  # 最终的有序结果
    pending = list(spans)  # 还没排进去的（拷一份，不动入参）
    # 最多迭代 len 轮即可收敛（层级深度 ≤ 节点数）。
    while pending:
        progressed = False  # 本轮有没有「至少收编一个」——用来识别卡死
        rest: list[Span] = []  # 本轮还排不进去的，留到下一轮
        for s in pending:
            # 可收编的条件：它是 root（无父），或它的父这一刻已经就位了。
            if s.parent_id is None or s.parent_id in placed:
                ordered.append(s)
                placed.add(s.span_id)  # 它就位后，它的孩子下一轮才可能被收编
                progressed = True
            else:
                rest.append(s)  # 父还没到，先搁置
        pending = rest
        if not progressed:
            # 一整轮一个都没收编 = 剩下的父都不在本批（数据异常，理论上不应发生）。
            # 兜底：把剩余的直接接到末尾，宁可顺序不完美也绝不在此处死循环。
            ordered.extend(pending)
            break
    return ordered
