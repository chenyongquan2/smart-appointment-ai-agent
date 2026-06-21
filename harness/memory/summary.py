"""摘要记忆层：接口、占位实现与生产级压缩（add-context-compaction）。

约定：当短期窗口外的较旧回合累积到阈值时，把它们压缩为一段摘要文本，以在不超出
上下文预算的前提下保留早期信息（用户约束、未完成槽位等）。

本文件含三部分：
- ``SummaryMemory`` Protocol：摘要契约（``summarize`` 输入窗外旧轮、返回摘要文本）；
- ``NoOpSummary``：Phase 4 留下的占位实现（始终返回空串，等价不压缩，作降级/测试基线）；
- ``LLMSummaryMemory``：生产级实现（add-context-compaction）——读/写分离、token 阈值
  触发、结构化 + 滚动压缩、持久化缓存、失败降级、可观测。

生产级实现的「算」与「用」分处请求两端（见 OpenSpec change add-context-compaction
design.md D1/D5/D7）：
- 写侧 ``compact_if_needed``：回合收尾时调用——判触发→取前序摘要→压缩→写缓存；
- 读侧 ``get_summary_hint``：请求开始时调用——纯读缓存、不碰 LLM。
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Protocol, Sequence, runtime_checkable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from harness.guardrails.retry import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_TIMEOUT,
    GuardrailExhausted,
    guarded_invoke,
)
from harness.memory.summary_schema import ConversationSummary
from harness.observability.tracer import NoopTracer, Tracer
from harness.runtime.session import Turn

logger = logging.getLogger(__name__)


@runtime_checkable
class SummaryMemory(Protocol):
    """摘要记忆契约。

    ``summarize`` 输入窗口外的较旧回合，返回一段摘要文本（供注入上下文）。
    """

    def summarize(self, old_turns: Sequence[Turn]) -> str:
        # 这是「契约」而非实现：Protocol 只规定方法签名（输入窗外旧轮、输出一段摘要文本），
        # 任何长这样的类都自动算作 SummaryMemory（结构化鸭子类型），无需显式继承。
        # 函数体 `...` 是占位，Protocol 不需要真正实现。
        ...


class NoOpSummary:
    """占位实现：不做任何压缩，始终返回空摘要。

    触发条件（约定）：``len(history) > window_turns`` 时本应调用 ``summarize``；
    本占位实现直接返回空串——窗口外旧回合不会以摘要形式注入上下文（它们仍被
    持久化保留）。整体对话流程不受影响、不抛异常。
    """

    def summarize(self, old_turns: Sequence[Turn]) -> str:  # noqa: D401
        # 设计意图：本 Phase 故意「先搭骨架、不上真功能」。返回空串 = 不产出任何摘要，
        # 于是窗外旧轮既不被压缩、也不注入上下文（裁掉它们的是 ShortTermMemory 的窗口）。
        # 这样做的好处：接口已定下、调用点已接通，后续真正实现压缩时只需替换本类，
        # 上层（loop/handler）一行都不用改。返回空串而非抛异常，保证现在流程也能正常跑通。
        return ""


# --------------------------------------------------------------------------- #
# 生产级压缩（add-context-compaction）
# --------------------------------------------------------------------------- #

# 默认触发参数（构造时可覆盖）。固定经验阈值，刻意不锚定模型窗口——本项目压缩的目的
# 不是「撞模型窗口天花板」（短会话撞不到），而是「捞回被自家小滑动窗口裁掉的早期信息」，
# 故用小阈值即可（见 design.md D2 / 学习笔记 §9）。
_DEFAULT_TRIGGER_TOKENS = 4000   # 未覆盖的窗外回合估算 token 超过此值才压缩
_DEFAULT_MIN_OLD_TURNS = 4       # 且未覆盖的窗外回合数 ≥ 此值，避免为零星短回合白调 LLM
_CHARS_PER_TOKEN = 4             # 与 guardrails.budget 同口径的粗估

_SUMMARY_SYSTEM_PROMPT = (
    "你是对话记忆压缩器。请把【更早的对话片段】压缩为结构化摘要，"
    "重点**完整保留**用户约束/偏好（如只要女技师、只能周末）与未完成事项（待确认的预约槽位），"
    "这些信息绝不能在压缩中丢失。"
    "若提供了【已有摘要】，请在其基础上并入新片段的信息（增量更新），不要遗漏已有摘要中的任何约束与待办。"
)


class LLMSummaryMemory:
    """生产级摘要记忆：token 阈值触发 + 结构化 + 滚动压缩 + 持久化缓存 + 降级 + 可观测。

    ── 先搞懂三个核心概念（下文反复出现，层层叠加）──────────────────────────────
    用一段进行到 6 条的对话举例（窗口设 4）：

        turn id │ 内容
           1    │ 我要约按摩，只要女技师   ┐ 窗外（旧）——AI 看不到原文
           2    │ 好的                     ┘
          ─────────────────────────────────
           3    │ 时长 60 分钟             ┐
           4    │ 好的                     │ 窗内 = 最近 window_turns 条
           5    │ 你们几点关门             │   ——AI 看得到原文
           6    │ 晚上 10 点               ┘

    - **turn id**：每条消息存进 DB（``conversation_turns`` 表）时自动分配的递增主键，
      即「这是第几条消息」的编号（1,2,3… 永不重复/回退）。我们拿它当书签用。
    - **window_turns**：**短期记忆窗口的大小**——「只把最近这么多条原文喂给 AI」（默认 10；
      单位是条消息，一问一答=两条）。它是一道分界线：线右边（近的）进上下文，线左边
      （旧的=窗外）被挤出。窗外旧消息正是压缩要接住的对象（否则像 id=1 的「只要女技师」
      聊久就被挤出、AI 失忆）。``out_of_window = rows[:-window_turns]``。
    - **covered_upto**：一个书签，值是某个 turn id，含义=「摘要已把 id ≤ 此值的消息都压进去了」。
      作用：下次压缩只处理「书签之后」(id > covered_upto) 的新出窗消息，老的不重读——像看书
      的书签，下次翻到下一页接着读。压缩后书签前移到本次覆盖的末条 id。

    一句话：window_turns 决定「谁掉出窗口要被压」，turn id 是每条消息的编号，
    covered_upto 用一个 turn id 当书签记住「压到第几条了」，好让滚动压缩不重复劳动。
    ──────────────────────────────────────────────────────────────────────────

    读/写分离（design.md D1/D7）：

    - 写侧 ``compact_if_needed(session_id)``：回合收尾时调用，判触发→滚动压缩→写缓存；
    - 读侧 ``get_summary_hint(session_id)``：请求开始时调用，纯读缓存、不碰 LLM。

    依赖（均为薄封装/可注入，便于离线测试）：
        llm: LangChain 聊天模型；经 ``with_structured_output(ConversationSummary)`` 产出结构化摘要。
        conversations_repo: 提供 ``get_turns(session_id)``（返回含 ``id`` 的升序回合）——
            ``covered_upto`` 游标需要稳定的 turn id（in-memory ``Turn`` 不带 id，故从持久层读）。
        summaries_repo: 提供 ``get_summary`` / ``upsert_summary``，摘要缓存的真相源。
        tracer: 可观测（Phase 6）；缺省 ``NoopTracer``。
        window_turns: 短期记忆窗口的大小（保留最近多少条消息，单位是条消息、非问答对），
            应与 ``ShortTermMemory`` 一致；窗外 = 除最近 N 条外的更早回合。
        summary_trigger_tokens / min_old_turns: 触发阈值（见上）。
        full_recompute_after_turns: 漂移纠偏开关——覆盖回合数达此上限触发一次全量重算；
            ``None`` 表示关闭（默认），本业务一般用不到。
    """

    def __init__(
        self,
        llm: BaseChatModel,
        conversations_repo: Any,
        summaries_repo: Any,
        *,
        tracer: Optional[Tracer] = None,
        window_turns: int = 10,
        summary_trigger_tokens: int = _DEFAULT_TRIGGER_TOKENS,
        min_old_turns: int = _DEFAULT_MIN_OLD_TURNS,
        full_recompute_after_turns: Optional[int] = None,
        llm_timeout: float = DEFAULT_TIMEOUT,
        llm_max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_sleep: Optional[Any] = None,
    ) -> None:
        self._conversations = conversations_repo
        self._summaries = summaries_repo
        self._tracer: Tracer = tracer or NoopTracer()
        self.window_turns = window_turns
        self.summary_trigger_tokens = summary_trigger_tokens
        self.min_old_turns = min_old_turns
        self.full_recompute_after_turns = full_recompute_after_turns
        self._llm_timeout = llm_timeout
        self._llm_max_attempts = llm_max_attempts
        self._retry_sleep = retry_sleep
        # 单一真相源：摘要 schema → 结构化输出链。with_structured_output 在协议层强制
        # 模型按 ConversationSummary 字段填写，丢失关键约束的风险远低于自由文本摘要。
        self._chain = llm.with_structured_output(ConversationSummary)

    # ---- 读侧：纯读缓存，不碰 LLM ---------------------------------------- #
    def get_summary_hint(self, session_id: str) -> str:
        """返回该会话已缓存摘要的渲染文本；无摘要或读取异常时返回空串。

        请求开始时由编排层调用，零 LLM 开销（摘要由上一轮的 ``compact_if_needed``
        预先算好落库）。失败安全降级为空串 → 等价不注入摘要 → 退回纯窗口。
        """
        try:
            row = self._summaries.get_summary(session_id)
        except Exception:  # noqa: BLE001 —— 读缓存失败不应影响请求
            logger.warning("读取会话摘要失败，本轮退回纯窗口", exc_info=True)
            return ""
        if not row:
            return ""
        return row.get("summary_text") or ""

    # ---- 写侧：回合收尾时滚动压缩并落库 ---------------------------------- #
    async def compact_if_needed(self, session_id: str) -> None:
        """按需把窗外未覆盖的较旧回合滚动压缩为摘要并写缓存（回合收尾时调用）。

        步骤：读 id-bearing 历史 → 取窗外回合 → 扣除已被缓存覆盖的部分 → 判 token/数量
        阈值 → （取前序摘要）滚动压缩 → upsert 缓存。任何 LLM 失败都降级（记 degraded、
        不写缓存、不抛异常）；读侧自然取不到新摘要而退回纯窗口。
        """
        span = self._tracer.start_span("summary.compact", attributes={"session_id": session_id})
        try:
            try:
                rows = self._conversations.get_turns(session_id)
            except Exception:  # noqa: BLE001
                logger.warning("读取会话历史失败，跳过本次压缩", exc_info=True)
                self._tracer.add_event(span, "error", {"type": "history_read_failed"})
                return

            # 窗外 = 除最近 window_turns 条外的更早回合；窗内的最近 N 条由短期记忆负责。
            out_of_window = rows[:-self.window_turns] if self.window_turns > 0 else list(rows)
            if not out_of_window:
                return  # 历史还没溢出窗口，无需压缩

            existing = None
            try:
                existing = self._summaries.get_summary(session_id)
            except Exception:  # noqa: BLE001
                logger.warning("读取既有摘要失败，按无摘要处理", exc_info=True)

            # covered_upto = 上次摘要的「书签」：已把历史压缩覆盖到的【末条 turn id】。
            #   语义：id ≤ covered_upto 的回合，信息都已在 existing["summary_text"] 里。
            #   首次（无摘要）置 0，等于「什么都还没覆盖」，下面会把全部窗外回合都算进去。
            covered_upto = existing["covered_upto"] if existing else 0
            full_recompute = self._should_full_recompute(out_of_window, covered_upto)

            # rows_to_summarize = 本次「要喂给 LLM 的窗外回合」。两分支喂的集合不同，
            # 但**收尾时覆盖范围相同**（都覆盖到 out_of_window 末条）→ 故 covered_to 在下方
            # if/else 外只算一次即对两者都成立（见 covered_to 处注释）。
            if full_recompute:
                # 漂移纠偏：丢掉前序摘要，把【全部】窗外回合原文重读一遍重算（贵，但纠正累积漂移）。
                # 注意这里是「全部」而非「新增」——含 id ≤ covered_upto 已压过的，故 prior_summary=None。
                rows_to_summarize = out_of_window
                prior_summary = None
                trigger_reason = "full_recompute"
            else:
                # 常规滚动：只并入「书签之后」的新出窗回合（id > covered_upto），它是 out_of_window
                # 的尾部切片，故其末条 == out_of_window 末条。id ≤ covered_upto 的老回合不再重读——
                # 其信息已在 prior_summary 里，这正是「滚动/增量压缩」省 token 的关键。
                rows_to_summarize = [r for r in out_of_window if r["id"] > covered_upto]
                prior_summary = existing["summary_text"] if existing else None
                trigger_reason = "rolling"

            if not rows_to_summarize:
                return  # 缓存已覆盖全部窗外回合 → 命中，不调 LLM

            # 阈值判定：未覆盖窗外回合的估算 token 与条数都要够，否则先不压缩（攒着）。
            approx_tokens = self._estimate_tokens(rows_to_summarize)
            if approx_tokens <= self.summary_trigger_tokens and len(rows_to_summarize) < self.min_old_turns:
                return  # 量太小，不值得一次 LLM 调用

            # ---- 触发压缩 ---- #
            # 本次压缩后，书签前移到「最后一条窗外回合的 id」——因为到这一刻为止，
            # 全部窗外回合（含刚并入的 rows_to_summarize）都已被摘要覆盖。它将作为新的 covered_upto 落库，
            # 供下一轮判断「哪些才是又新掉出窗口、还没压过的回合」。
            covered_to = out_of_window[-1]["id"]
            try:
                summary_text = await self._summarize_rows(rows_to_summarize, prior_summary)
            except GuardrailExhausted:
                # 降级：LLM 重试耗尽 → 不写缓存、记 degraded、不抛；读侧退回纯窗口。
                logger.warning("摘要压缩 LLM 调用失败，降级（不写缓存）", exc_info=True)
                self._tracer.add_event(span, "error", {"type": "summarize_failed", "degraded": True})
                return

            try:
                self._summaries.upsert_summary(session_id, summary_text, covered_to)
            except Exception:  # noqa: BLE001
                logger.warning("写入摘要缓存失败", exc_info=True)
                self._tracer.add_event(span, "error", {"type": "cache_write_failed"})
                return

            self._tracer.add_event(
                span,
                "compacted",
                {
                    "trigger_reason": trigger_reason,
                    "tokens_before": approx_tokens,
                    "tokens_after": self._estimate_text_tokens(summary_text),
                    "covered_upto": covered_to,
                    "new_turns": len(rows_to_summarize),
                    "degraded": False,
                },
            )
        finally:
            self._tracer.end_span(span)

    async def summarize(
        self, old_turns: Sequence[Any], prior_summary: Optional[str] = None
    ) -> str:
        """把一组（窗外）回合压缩为渲染后的摘要文本（异步，经 LLM）。

        ``SummaryMemory`` 契约的生产实现；因需调用异步 LLM 而为 async（``NoOpSummary``
        仍是同步的占位基线）。``old_turns`` 接受带 ``role``/``content`` 的 ``Turn`` 或 dict。
        """
        return await self._summarize_rows(old_turns, prior_summary)

    # ---- 内部 ---------------------------------------------------------- #
    async def _summarize_rows(
        self, rows: Sequence[Any], prior_summary: Optional[str]
    ) -> str:
        """构造提示、经护栏调用结构化输出链、渲染为摘要文本。"""
        transcript = "\n".join(
            f"{self._row_role(r)}：{self._row_content(r)}" for r in rows
        )
        human_parts: List[str] = []
        if prior_summary:
            human_parts.append(f"【已有摘要】\n{prior_summary}")
        human_parts.append(f"【更早的对话片段】\n{transcript}")
        messages = [
            SystemMessage(content=_SUMMARY_SYSTEM_PROMPT),
            HumanMessage(content="\n\n".join(human_parts)),
        ]
        # 经 guarded_invoke 套超时+重试（只读、幂等，可安全重试）；耗尽抛 GuardrailExhausted
        # 由调用方降级。结构化输出在协议层保证返回合法 ConversationSummary。
        summary: ConversationSummary = await guarded_invoke(
            lambda: self._chain.ainvoke(messages),
            timeout=self._llm_timeout,
            max_attempts=self._llm_max_attempts,
            sleep=self._retry_sleep,
        )
        return summary.render()

    def _should_full_recompute(self, out_of_window: Sequence[Any], covered_upto: int) -> bool:
        """漂移纠偏：覆盖回合数达 ``full_recompute_after_turns`` 上限则全量重算一次。"""
        if self.full_recompute_after_turns is None:
            return False  # 开关关闭（默认）
        covered_count = sum(1 for r in out_of_window if r["id"] <= covered_upto)
        return covered_count >= self.full_recompute_after_turns

    def _estimate_tokens(self, rows: Sequence[Any]) -> int:
        """估算一组回合的 token（字符/4，与 guardrails.budget 同口径）。"""
        total_chars = sum(len(self._row_content(r)) for r in rows)
        return total_chars // _CHARS_PER_TOKEN

    @staticmethod
    def _estimate_text_tokens(text: str) -> int:
        return len(text) // _CHARS_PER_TOKEN

    @staticmethod
    def _row_role(row: Any) -> str:
        return row["role"] if isinstance(row, dict) else getattr(row, "role", "")

    @staticmethod
    def _row_content(row: Any) -> str:
        return row["content"] if isinstance(row, dict) else getattr(row, "content", "")
