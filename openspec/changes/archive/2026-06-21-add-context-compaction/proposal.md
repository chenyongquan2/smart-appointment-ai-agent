## Why

Phase 4 落地短期窗口与长期偏好后，把「摘要记忆」(context compaction) 刻意留成 `NoOpSummary` 占位桩：超出短期窗口的较旧回合被 `ShortTermMemory` 直接裁掉、**不以任何形式注入上下文**（仅持久化在 DB）。这意味着长会话里早期表达的关键约束（性别偏好、时间限制、已确认/未完成的预约槽位）会随对话变长而"失忆"。

要让 harness 在生产环境可信地处理长会话，需要把这个桩替换为一个**生产级、对齐 harness 标准的压缩实现**：在不超出上下文预算的前提下，把窗外旧回合压缩为保留关键信息的结构化摘要，并具备触发策略、缓存、容错降级与可观测性。

## What Changes

- **替换 `NoOpSummary` 为生产级 `SummaryMemory` 实现**（保持 `SummaryMemory` Protocol 接口签名不变，上层调用契约零破坏）：
  - **按 token 预算触发**压缩（窗口轮数作为粗略兜底触发条件），复用既有 `estimate_tokens`。
  - **结构化摘要**：用 structured output 让 LLM 产出含「关键实体 / 已做决策 / 未完成事项 / 用户约束」的结构化摘要，再渲染为一段提示文本，避免丢失预约槽位类信息。
  - **滚动/增量压缩**（summary-of-summary）：已有摘要 + 新出窗回合 → 新摘要，避免每次全量重总结。
  - **摘要缓存与失效**：摘要持久化（复用 SQLite + Repository 风格），命中复用；会话历史变更/分叉时失效。
  - **容错降级**：摘要 LLM 调用超时/失败时优雅退回纯窗口裁剪（对齐 Phase 5 护栏），不崩 loop。
  - **可观测**：压缩动作经 Phase 6 `tracer` 记录（触发原因、压缩前后 token、耗时、是否降级）。
- **接入编排**：`chat_handler` / 记忆组装层在窗外回合存在时调用 `SummaryMemory`，把摘要作为上下文（注入在系统提示之后、短期窗口之前）。短期窗口与长期偏好职责不变；关键长期偏好仍归 `LongTermMemory`，不靠对话摘要兜底。
- **回归与评估**：补单测（触发阈值、滚动压缩、缓存命中、降级路径）与 `evals/` 长会话对照用例，防回归。

## Capabilities

### New Capabilities
<!-- 无新增独立能力：压缩属于既有 session-memory 能力的需求升级 -->

### Modified Capabilities
- `session-memory`: 「摘要记忆层接口（本 Phase 留 stub）」需求从"仅占位、不做实际压缩"升级为"生产级压缩"——新增按 token 预算触发、结构化摘要内容、滚动压缩、摘要持久化与失效、LLM 失败时降级到窗口裁剪、压缩动作可观测等行为级要求。

## Impact

- **代码**：
  - `harness/memory/summary.py`（替换实现，接口不变）；可能新增 `harness/memory/` 下的摘要内容 schema 文件（一个概念一个文件）。
  - `api/chat_handler.py` / 记忆组装：接入摘要注入。
  - 摘要持久化：新增 `ConversationSummary` 模型 + Repository（复用既有 `SessionManager` / `session_scope`，风格对齐 `ConversationRepository`，不改既有 Repository）。
- **依赖**：LLM 经 `config/model_provider.py`，无新增第三方依赖（token 估算复用 `guardrails/budget.estimate_tokens`）。
- **不动**：`SummaryMemory` 接口、`ShortTermMemory`、`LongTermMemory`、`services/`、RAG。
- **成本/延迟**：压缩触发时多一次 LLM 调用——靠 token 预算触发 + 缓存复用 + 仅在长会话触发来控制；降级路径保证最坏情况不劣于当前桩行为。
