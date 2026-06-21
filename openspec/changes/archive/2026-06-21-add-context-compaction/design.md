## Context

Phase 4 建了分层记忆：`ShortTermMemory`（最近 N 轮窗口）、`LongTermMemory`（跨会话偏好）、`SummaryMemory`（摘要，留 `NoOpSummary` 桩）。当前窗外旧回合被 `ShortTermMemory.to_messages` 用 `history[-N:]` 直接裁掉——既不压缩也不注入，仅靠 `ConversationRepository` 持久化。`chat_handler.ProcessUserInput_stream` 是编排入口：取历史 → 写用户输入 → 驱动无状态 `AgentLoop` → 回写回复。`AgentLoop` 保持无状态，记忆组装在 handler 完成。

既有可复用资产：`guardrails/budget.estimate_tokens`（字符/4 粗估，跨 provider）、`guardrails/retry.guarded_invoke`（超时+重试）、`observability/tracer`（span/event）、`config/model_provider.create_chat_model`、`db` 的 `SessionManager`/`session_scope` + Repository 风格、Phase 1 的 structured output 经验。

约束（CLAUDE.md / project.md）：一个概念一个文件；结构化输出优先；工具是 services 薄封装；不重写 services/db/RAG；`SummaryMemory` 接口不变以保上层零改动；改动相关 `uv run pytest` + `evals/` 必须绿。

## Goals / Non-Goals

**Goals:**
- 用生产级压缩替换 `NoOpSummary`，保持 `SummaryMemory` Protocol 签名不变。
- token 预算触发；结构化摘要保留关键约束/未完成槽位；滚动增量压缩；摘要持久化+失效；LLM 失败降级到窗口裁剪；压缩动作可观测。
- 接入 `chat_handler` 的记忆组装，注入位置：系统提示 → 摘要 → 短期窗口 → 当前输入。
- 回归测试 + `evals/` 长会话对照。

**Non-Goals:**
- 不改 `ShortTermMemory` / `LongTermMemory` 行为，不改 `AgentLoop` 的核心循环。
- 不引入 tiktoken 等精确计费依赖（沿用粗估）。
- 不做语义级去重 / 向量化记忆检索（超出本 change）。
- 不把关键长期偏好迁进摘要——偏好仍归 `LongTermMemory`。

## Decisions

> **本节决策已经 grill-me 逐条拍板（Q1–Q8）**；下文标 ⟨grill⟩ 处为定稿口径。

### D1 — 接口边界：读/写分离，`summarize` 签名不变 ⟨grill Q5/Q6⟩
现有 Protocol 是 `summarize(old_turns) -> str`，保留不变作为"给定一组窗外回合（+ 可选前序摘要）产出摘要文本"的纯函数契约。生产逻辑因 Q5-B（回合结束后台算）拆成**读、写两条路径**：
- **写侧** `compact_if_needed(session_id, history, window_turns) -> None`：在回合收尾时调用——判触发 → 取前序摘要 → `summarize` → 写缓存。无返回（产物落 DB）。
- **读侧** `get_summary_hint(session_id) -> str`：请求开始时调用——**纯读缓存**，不调 LLM；无摘要返回空串。
- *为何*：摘要的"算"与"用"在生命周期里分处两端（见 D7）；读侧零延迟、写侧不挡关键路径；`summarize` 签名零破坏，`NoOpSummary` 仍可顶替。
- *备选*：单一 `build_summary_hint`（请求内同步算）→ 被 Q5-B 否决（卡首 token）。

### D2 — 触发：固定经验阈值（不锚定模型窗口）⟨grill Q1⟩
窗外回合 = `history[:-N]`。用 `estimate_tokens` 估其体量，超过**固定阈值** `summary_trigger_tokens`（默认 ≈4000）且窗外回合数 ≥ `min_old_turns`（默认 4）才压缩。两值均可配。
- *为何*：本项目压缩的**目的不是"撞模型窗口天花板"**（短会话撞不到），而是"捞回被自家小窗口（10 轮）裁掉的早期信息"——目的不同，触发就不该像 Claude Code 那样锚定模型窗口百分比，固定小阈值才对（详见学习笔记 §9）。
- *备选*：相对模型窗口比例 → 要新引入窗口大小配置、各 provider 差异大，否决；复用 `AgentLoop.max_tokens` → 它当前禁用且管的是"单请求 loop 内累计"，与跨轮历史压缩是两件事，否决。

### D3 — 摘要内容：structured output（一个概念一个文件）
新增 `harness/memory/summary_schema.py`：Pydantic 模型 `ConversationSummary`，字段含 `key_entities` / `decisions` / `open_items` / `user_constraints`（含预约槽位）。`summarize` 经 `config.model_provider` 的模型 + structured output 产出该对象，再 `render()` 成提示文本。
- *为何*：防止自由文本摘要丢掉槽位类关键信息；与 Phase 1 结构化输出一脉相承、可单测。
- *备选*：自由文本摘要 → 不可控、易丢槽位，否决。

### D4 — 滚动压缩：summary-of-summary，纠偏开关默认关 ⟨grill Q3⟩
`summarize` 输入 = 前序摘要文本（若有）+ 新出窗回合。prompt 指示模型"在已有摘要基础上并入新信息、保留所有未完成项与约束"。
- *为何*：本项目已有滑动窗口，滚动缓冲摘要（LangChain 流派）是天然搭配；避免每次重读全部历史，覆盖范围随会话单调增长。Claude Code 的"高水位全量"是为撞窗口设计的，与本项目"持续滑出"模式不匹配（学习笔记 §9）。
- *漂移纠偏*：保留 `full_recompute_after_turns` 开关（覆盖回合数达上限触发一次全量重算），**默认关闭/设很大**——本业务到不了需要纠偏的会话长度；结构化 schema 已强约束保留约束/未完成项。
- *备选*：每次全量重算 → 越往后越贵且与滑出模式不符，否决。

### D5 — 缓存与失效：新增 `ConversationSummary` 表，`covered_upto = 末条 turn id` ⟨grill Q2/Q4⟩
新增 `db/models` 的 `ConversationSummary`（session_id、summary_text、`covered_upto`=被压缩进摘要的**最后一条 `ConversationTurn` 的 DB id**、updated_at）与 `ConversationSummaryRepository`（复用 `session_scope`，风格对齐 `ConversationRepository`，不改既有 Repository）。命中判定：摘要已覆盖到 id≤`covered_upto`，写侧把"id 在此之后、且仍属窗外"的新回合滚动并入；id 对不上（被删/回退/换 session）即失效全量重算。
- *为何*：`ConversationTurn` 已有自增 `id`，是稳定、单调、抗并发的游标；append-only 历史下正常只走"id 增长→滚动"。复用既有 SQLite + Repository 模式，重启可恢复，命中复用省 LLM 调用。
- *备选*：回合计数 → 并发交错写易错位，否决；内容哈希 → 为"原地编辑历史"准备，但本表 append-only，过度设计，否决；纯内存缓存 → 重启丢失，与"持久化/生产"不符，否决。

### D6 — 容错降级：`guarded_invoke` + 兜底空串
摘要 LLM 调用经 `guarded_invoke`（超时+有限重试，复用 Phase 5）；耗尽/异常时写侧 `compact_if_needed` 捕获、不写缓存、记 `degraded`；读侧自然取不到摘要 → 返回空串 → 退回纯窗口（即当前桩行为，安全下界）。
- *为何*：对齐 Phase 5"LLM 失败不崩 loop"；最坏情况不劣于现状。

### D7 — 编排：读/写分处请求两端，注入为独立 `SystemMessage` ⟨grill Q5/Q6/Q7⟩
- **读侧（请求开始）**：`chat_handler` 取短期窗口时调 `get_summary_hint(sid)`（纯读缓存），把非空摘要包成**独立 `SystemMessage`** 置于 `history` 列表**首条**，落在 spec 要求的"系统提示之后、短期窗口之前"。与长期偏好（走 `system_suffix`）**物理分开**。
- **写侧（回合收尾）**：在 [chat_handler.py] 回写助手回复**之后**、`ProcessUserInput_stream` 生成器返回**前**，**inline-after-stream** 同步调 `compact_if_needed(...)`（响应已流式送达，用户无感；任务确定性完成、异常可接住、可单测）。**不用** `asyncio.create_task` 的 fire-and-forget（ASGI 下游离 task 易被请求结束打断、丢任务、难 trace）。
- *并发兜底*：用户极快连发两条、下一轮启动时上一轮摘要尚未算完 → 读侧取到旧摘要或空 → 退回纯窗口，下下轮再用上，不阻塞。
- *为何*：摘要 LLM 调用彻底移出关键路径（首 token 零额外延迟），同时避开 fire-and-forget 可靠性坑；保持 `AgentLoop` 无状态、签名不变。

### D8 — 可观测
压缩（写侧）在 tracer 下开一个 event/span，记录 `trigger_reason`、`tokens_before`/`tokens_after`、`latency`、`degraded`。handler 已有 tracer 接入点（Phase 6）。

### D9 — 验证：机制单测（fake LLM）+ 独立 evals 对照 ⟨grill Q8⟩
- **单测（`tests/`，确定性、不触网）**：fake LLM 返回固定假摘要，只验**机制**——阈值触发/不触发、滚动时喂入"前序摘要+新回合"、缓存命中不重复调、LLM 异常时降级不崩、tracer 收到 event、注入位置正确。随 `uv run pytest` 跑。
- **evals（`evals/`，真 LLM，少量，不进主回归）**：长会话用例（早期设"只要女技师"→ 灌 >10 轮挤出窗口 → 后续"帮我约"），断言结果**不违反**早期约束，作为压缩"质量"对照。
- *为何*：对齐项目铁律——单测确定性不触网、`evals/` 做重构前后对照；不把真 LLM 波动引进主回归，保住"成功静默、只报错"。

## Risks / Trade-offs

- **额外 LLM 调用带来延迟/成本** → token 预算触发 + 缓存命中复用 + 仅长会话触发；短会话主场景几乎零开销。
- **摘要丢失关键信息（压缩有损）** → 结构化 schema 强制保留约束/未完成项；evals 长会话用例断言早期约束在后续轮次仍被遵守。
- **缓存失效判定不准（历史分叉/截断）** → 本业务历史单调追加，分叉罕见；采用保守策略"边界不匹配即重算"，宁可多算不可用错摘要。
- **滚动摘要漂移/累积误差**（多次 summary-of-summary 信息衰减）→ 摘要里显式保留"未完成项/约束"清单；可设覆盖回合数上限后做一次全量重算（列为 Open Question）。
- **接口张力**（生产逻辑塞进固定签名）→ 读/写分离（D1）：`get_summary_hint`/`compact_if_needed` 承接编排，`summarize` 保持纯函数契约不变。
- **写侧 inline 让回合协程多活 ~1s**（D7）→ 响应已流式送达、用户无感；换取确定性完成与可测性，优于 fire-and-forget 丢任务。

## Migration Plan

1. 加 `ConversationSummary` 模型 + Repository（仅新增表，不改既有表/Repository）。
2. 实现 `summary_schema.py` + 生产级 `SummaryMemory`（`summarize` + `compact_if_needed` + `get_summary_hint`），保留 `NoOpSummary` 作为降级/测试实现。
3. `chat_handler`：读侧注入摘要 `SystemMessage`；写侧回合收尾 inline 调 `compact_if_needed`。
4. 机制单测 + evals 长会话对照，绿后归档。
- **回滚**：读侧不注入摘要（或换 `NoOpSummary`）即恢复 Phase 4 行为；新增表不影响既有流程。

## Open Questions

（grill-me Q1–Q8 已逐条拍板，无遗留未决项。）

- 旁注：`AgentLoop.max_tokens` 当前在 `chat_handler` 未配置（默认 `None`，预算护栏关闭）。摘要本属上下文，未来若启用预算护栏应一并计入——但本 change 不负责开启该护栏，仅记录此事实。
