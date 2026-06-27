"""采样 SpanExporter：按整条 trace 决定留/弃，错误优先留存（改造 7 · 在线评估闭环）。

design.md D2：默认全量落盘；命中失控信号（max_steps / 工具异常 / guardrail / spin）的 trace
**必留**、不受采样率影响；``sample_rate``（默认 1.0）只对「非错误」trace 按比例采。

为何包一层而非在 ``FileSpanExporter`` 内逐 span 判：采样单位是**整条 trace**——逐 span 判会切断
同一 trace 的 span 树（留一半丢一半）。故本 exporter 按 ``trace_id`` 缓冲 span，待该 trace 的 root
span（``parent_id is None``）结束导出时，对整组 span 跑一次留/弃决策，再整组转发给内层 exporter。

不得抛（同 exporter 协议）：``export`` 内吞一切异常，绝不影响主循环。
"""

from __future__ import annotations

import logging
import random
from typing import Callable, Optional

from harness.observability.exporter import SpanExporter
from harness.observability.span import Span
from harness.observability.trace_signals import is_bad_trace

__all__ = ["SamplingSpanExporter"]

_DEFAULT_LOGGER = "harness.observability"


class SamplingSpanExporter:
    """按整条 trace 采样、错误优先留存的 exporter 包装器。

    Args:
        inner: 真正落地的 exporter（如 ``FileSpanExporter``）。
        sample_rate: 「非错误」trace 的留存概率（0.0–1.0）；默认 1.0（全量留）。
            错误 trace 不受此影响、始终留。
        rng: 返回 ``[0,1)`` 浮点的随机源；默认 ``random.random``，测试可注入定值以确定性断言。
        logger: 失败 warning 用 logger。
    """

    def __init__(
        self,
        inner: SpanExporter,
        sample_rate: float = 1.0,
        rng: Optional[Callable[[], float]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._inner = inner
        self._sample_rate = sample_rate
        self._rng = rng or random.random
        self._logger = logger or logging.getLogger(_DEFAULT_LOGGER)
        # 按 trace_id 缓冲尚未决策的 span（root 结束时一次性决策并清空该 trace 的缓冲）。
        self._buffers: dict[str, list[Span]] = {}

    def export(self, span: Span) -> None:
        """缓冲 span；遇 root 结束则对整条 trace 做留/弃决策。失败仅 warning，不抛。"""
        try:
            buf = self._buffers.setdefault(span.trace_id, [])
            buf.append(span)
            # root span（无父）结束 = 整条 trace 收尾（AgentLoop 在最外层 finally 关 root，
            # 故此时该 trace 的全部 child span 已先到达缓冲）。
            if span.parent_id is None:
                self._decide_and_flush(span.trace_id)
        except Exception:  # noqa: BLE001 —— 可观测不得拖垮主流程
            self._logger.warning("SamplingSpanExporter 处理 span 失败，已忽略", exc_info=True)

    def _decide_and_flush(self, trace_id: str) -> None:
        buf = self._buffers.pop(trace_id, [])
        if not buf:
            return
        # 错误优先：命中任一坏信号则必留；否则按采样率掷一次。
        keep = is_bad_trace(buf) or self._rng() < self._sample_rate
        if keep:
            for s in buf:
                self._inner.export(s)
