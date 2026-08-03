"""Tracer：开关 span、记录事件、结束时导出（Phase 6 可观测层）。

一次请求的用法（见 agent_loop 接入）::

    tracer = Tracer(exporter)
    root = tracer.start_span("agent_loop.run", attributes={"session_id": sid})
    for step in ...:
        step_span = tracer.start_span("step", parent=root)
        tracer.add_thought(step_span, ai_text)
        tracer.add_tool_call(step_span, name, args)
        tracer.add_observation(step_span, name, result)
        tracer.set_tokens(step_span, n_approx)
        tracer.end_span(step_span)
    tracer.end_span(root)

设计要点（design.md D1/D3）：
- 父子关系由 ``parent`` 显式传入，``trace_id`` 由 root 生成、child 继承——不依赖
  OpenTelemetry 隐式 context，手写 async 循环里不会断树。
- ``clock`` / ``wall_clock`` / ``id_factory`` 可注入，使 latency、绝对时间与 id 在单测中
  确定性可断言。``clock`` 是单调时钟（算 latency），``wall_clock`` 是墙钟（定位时间点），
  两者并存不混用——详见 ``span.py`` 的说明。
- token 记为近似（``approximate=True``），复用 guardrails 的 ``estimate_tokens`` 口径。

``NoopTracer`` 实现同样接口但什么都不做，供 ``AgentLoop`` 在未注入 tracer 时退化
（向后兼容，design.md D2）。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from harness.observability.exporter import SpanExporter
from harness.observability.span import Span, SpanEvent

__all__ = ["Tracer", "NoopTracer"]


class Tracer:
    """开/关 span 并在结束时经 exporter 导出。

    Args:
        exporter: span 输出后端（实现 ``SpanExporter.export``）。
        clock: 单调时钟，仅用于算 latency；默认 ``time.perf_counter``，测试可注入。
        wall_clock: 墙钟，用于给 span 盖绝对时间戳；默认 ``datetime.now(timezone.utc)``，
            测试可注入固定时刻以获得确定性断言。
        id_factory: 生成 trace_id/span_id 的工厂；默认 uuid4 十六进制，测试可注入
            计数器以获得确定性 id。
    """

    def __init__(
        self,
        exporter: SpanExporter,
        clock: Optional[Callable[[], float]] = None,
        id_factory: Optional[Callable[[], str]] = None,
        wall_clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._exporter = exporter
        # clock 只用于算 latency，故要单调时钟（perf_counter，不受系统时间回拨影响）。
        # 可注入：测试传一个「每调一次 +1」的假时钟，latency 就成了确定值，可精确断言。
        self._clock = clock or time.perf_counter
        # id_factory 默认产 uuid4 十六进制串（全局唯一）；测试可注入计数器 1、2、3…
        # 让 trace_id / span_id 变可预测，断言 span 树结构时不必匹配随机串。
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        # 墙钟另立一个可注入口，不复用 clock：clock 必须单调（算 latency），墙钟必须绝对
        # （定位时间点），两个需求不可能由同一个时钟同时满足。缺省取带 tz 的 UTC——
        # 裸 datetime.now() 会产出无时区信息的串，跨机器/跨时区读时无从判断基准。
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))

    def start_span(
        self,
        name: str,
        parent: Optional[Span] = None,
        attributes: Optional[dict[str, Any]] = None,
    ) -> Span:
        """开一个 span。无 ``parent`` 即 root（生成新 trace_id）；有则继承 trace_id。"""
        # ★ 整套串联机制的核心：trace_id 标识「一整次请求」。
        #   有父 → 直接复用父的 trace_id（全树同一个 id，回放时能把整请求捞齐）；
        #   无父 → 这是 root span，新造一个 trace_id 作为本次请求的「身份证」。
        trace_id = parent.trace_id if parent is not None else self._id_factory()
        return Span(
            trace_id=trace_id,
            span_id=self._id_factory(),  # 每个 span 自己的唯一 id（无论 root 还是 child）
            # ★ 父子关系靠这一行「显式」持有：child 把父的 span_id 抄进自己的 parent_id。
            #   不依赖 OTel 的隐式 context 传播，故在手写 async 循环里也绝不会断树。
            parent_id=parent.span_id if parent is not None else None,  # root 无父 → None
            name=name,
            start=self._clock(),  # 记开始时刻，end_span 时减出 latency
            # 同时盖一个绝对时间戳：单调 clock 的读数跨进程无意义，落盘后没法回答
            # 「这条 trace 是什么时候的」。isoformat() 带 tz 偏移，故串本身自带基准。
            started_at=self._wall_clock().isoformat(),
            # 拷一份再存：避免外部后续改了传入 dict 反过来污染本 span 的属性。
            attributes=dict(attributes or {}),
        )

    def end_span(self, span: Span) -> None:
        """结束 span（记结束时刻）并导出。导出异常被吞掉，绝不影响主流程。"""
        span.end = self._clock()  # 盖上结束时刻；之后 span.latency 才有值（end - start）
        try:
            self._exporter.export(span)  # 交给后端落地（写日志 / 发 OTel / 进内存收集器）
        except Exception:  # noqa: BLE001 —— 故意吞掉「全部」导出异常
            # ★ 关键设计取舍：可观测性是「附属能力」，绝不能因为日志写失败、OTel 后端
            #   挂了就把用户的正常请求也带崩。故这里静默吞掉——宁可丢一条 trace。
            pass

    # —— 事件记录便捷方法（下面几个都是往 span.events 里按发生顺序追加一笔）——
    def add_event(self, span: Span, kind: str, payload: dict[str, Any]) -> None:
        # 所有事件的统一底座：kind 标类型（thought/tool_call/observation…），payload 装内容。
        span.events.append(SpanEvent(kind=kind, payload=payload))

    def add_thought(self, span: Span, text: str) -> None:
        """记录该步 LLM 产出的文本/决策。"""
        self.add_event(span, "thought", {"text": text})

    def add_tool_call(
        self, span: Span, name: str, args: Any, identity: Optional[dict[str, Any]] = None
    ) -> None:
        """记录一次工具调用（名称 + 参数），可带该次调用的**身份参数**。

        Args:
            identity: 原始参数剔除该工具声明的宽度类参数后剩下的部分
                （见 ``harness/tools/base.Tool.identity_args``）。缺省 ``None`` 时
                payload 与引入本参数前完全一致（向后兼容）。

        **为何身份参数在记录时传入、而不由判定侧自己剔**：``trace_signals`` 是只看 span 的
        纯函数、拿不到 ``ToolRegistry``，唯一的自行实现方式是硬编码 ``{"window","limit",
        "top_k"}`` 这类参数名白名单——那等于把**域内容嵌进域无关运行时**（与记忆层那三处
        已知泄漏同类）。故由持有 registry 的 ``AgentLoop`` 算好传进来，判定侧只读结构。
        与 ``add_observation`` 提取 ``error_kind`` 是同一手法。
        """
        payload: dict[str, Any] = {"name": name, "args": args}
        if identity is not None:
            payload["identity"] = identity
        self.add_event(span, "tool_call", payload)
        # 同时挂到 attributes 便于检索/给 OTel span 当属性。
        # 用 setdefault：一步若调多个工具，只认「第一个」做该 span 的代表工具名，
        # 不被后续调用覆盖（attributes 是给人按工具名快速筛 span 用的索引字段）。
        span.attributes.setdefault("tool_name", name)

    def add_observation(self, span: Span, name: str, result: Any) -> None:
        """记录工具结果。

        除字符串化的结果外，还会在 ``str()`` 化**之前**窄提取 ``error_kind``——那是
        service 层自行分类的失败标记（如 ``services/vlog.py`` 的 timeout /
        connect_failed），此时工具是**正常返回**、loop 层面没有任何异常，故不提取的话
        ``trace_signals`` 无从判定（见该模块 docstring 记的那次静默漏报）。
        """
        payload: dict[str, Any] = {"name": name, "result": str(result)}
        # ★ 只提 error_kind 这一个键，且必须在 str() 化之前——之后就只剩 str(dict) 的
        #   排版，而那不是契约（黄金准则：结构化输出 > 字符串解析）。
        #   刻意不把整个结果对象塞进 payload：vlog 的结果含真实生产日志正文，体积大且
        #   含业务内容；payload 只该留判定所需的最小结构。
        error_kind = _extract_error_kind(result)
        if error_kind is not None:
            payload["error_kind"] = error_kind
        self.add_event(span, "observation", payload)

    def set_tokens(self, span: Span, tokens: int, approximate: bool = True) -> None:
        """记录该 span 的 token（近似值，标注 approximate）。"""
        span.attributes["tokens"] = tokens
        # ★ 显式标注 approximate=True：这个数来自 guardrails 的 estimate_tokens 估算，
        #   不是 provider 回的精确用量。打上标记，看 trace 的人不会误当成账单级精确值。
        span.attributes["tokens_approximate"] = approximate


class NoopTracer(Tracer):
    """什么都不做的 tracer：``AgentLoop`` 未注入 tracer 时退化使用（向后兼容）。

    复用 ``Tracer`` 的 span 构造逻辑（便于调用方拿到 span 对象做父子传参），但
    ``end_span`` 不导出、事件方法被覆盖为 no-op，故不产生任何输出、零副作用。
    """

    def __init__(self) -> None:
        # 不需要真实 exporter；导出已被 end_span 覆盖为 no-op。
        # 仍塞一个「啥也不导」的占位 exporter，只为满足父类 __init__ 的签名。
        super().__init__(exporter=_NULL_EXPORTER)

    # ★ 为何「继承 Tracer 而非另起接口」：start_span 不覆盖，直接复用父类那套——
    #   仍真的造出 Span 对象（带 trace_id/span_id），故 AgentLoop 那边 root/step 的
    #   父子传参（parent=root）照常能跑，调用方代码一行都不用改（向后兼容）。
    #   下面这几个「真正会产生副作用/输出」的方法才覆盖成空操作。

    def end_span(self, span: Span) -> None:  # noqa: D401 —— 覆盖为 no-op
        span.end = self._clock()  # 只盖结束时刻（保持 span 对象自洽），但「绝不导出」

    def add_event(self, span: Span, kind: str, payload: dict[str, Any]) -> None:
        pass  # 不记任何事件 → 连 thought/tool_call/observation 也一并空转（都走 add_event）

    def set_tokens(self, span: Span, tokens: int, approximate: bool = True) -> None:
        pass  # 不写 token 属性


def _extract_error_kind(result: Any) -> Optional[str]:
    """从工具返回值里取 ``error_kind``（Mapping 取键、否则取属性）；取不到返回 ``None``。

    **自身绝不抛**：工具返回什么类型都有，怪对象的 ``get`` / ``__getattr__`` 都可能炸。
    可观测是附属能力，沿用 ``end_span`` 吞导出异常的同一取舍——提取失败就当没提取到，
    绝不能因为埋点把用户的正常请求带崩。

    ⚠ **只认 ``error_kind``，不泛化成「任何错误类字段」**：``services/repo.py`` 用
    ``status`` 表达结果，其中 ``need_clone`` 等是**显式定义的正常引导状态**
    （``GUIDE_STATUS``）。把它们当失败会制造误报候选，而 triage 的价值全在信噪比。
    """
    try:
        if isinstance(result, Mapping):
            value = result.get("error_kind")
        else:
            value = getattr(result, "error_kind", None)
    except Exception:  # noqa: BLE001 —— 见上：埋点绝不拖垮主流程
        return None
    # 仅认非空字符串：None（未失败）、以及其它类型的怪值都视为「没有分类」。
    return value if isinstance(value, str) and value else None


class _NullExporter:
    # 占位用：NoopTracer 的 end_span 已不调 export，所以这个 export 实际永不触发。
    def export(self, span: Span) -> None:  # pragma: no cover - 永不被调用
        pass


_NULL_EXPORTER = _NullExporter()  # 模块级单例，所有 NoopTracer 共用，无需每次新建
