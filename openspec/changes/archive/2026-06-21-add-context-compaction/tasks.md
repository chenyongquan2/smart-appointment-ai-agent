## 1. 持久化层（摘要缓存）

- [x] 1.1 在 `db/models` 新增 `ConversationSummary` 模型（session_id、summary_text、covered_upto、updated_at），仅新增表，不改既有模型
- [x] 1.2 新增 `db/repositories/conversation_summary_repository.py`，复用 `session_scope`，风格对齐 `ConversationRepository`：`upsert_summary` / `get_summary`
- [x] 1.3 在 `DatabaseRouter` 暴露 `summaries` 访问点（对齐 `conversations` / `user_behavior`）
- [x] 1.4 Repository 单测：写入/读取/覆盖（upsert）/不存在返回 None

## 2. 摘要内容 schema

- [x] 2.1 新增 `harness/memory/summary_schema.py`：Pydantic `ConversationSummary`（key_entities / decisions / open_items / user_constraints）+ `render()` 渲染为提示文本
- [x] 2.2 schema 单测：字段约束、render 输出包含各关键段

## 3. 生产级 SummaryMemory（读/写分离 — D1）

- [x] 3.1 在 `harness/memory/summary.py` 实现生产级类（保留 `SummaryMemory` Protocol 与 `NoOpSummary` 不动）：`summarize(old_turns, prior_summary=None) -> str` 经 `config.model_provider` + structured output 产出 `ConversationSummary` 并 render
- [x] 3.2 `summarize` 的 LLM 调用经 `guardrails.retry.guarded_invoke`（超时+重试）
- [x] 3.3 写侧 `compact_if_needed(session_id)`：以固定阈值触发（估窗外回合 > `summary_trigger_tokens`≈4000 且窗外回合数 ≥ `min_old_turns`≈4，均可配）；命中缓存则不动，否则取前序摘要滚动压缩、写缓存（注：从 conversations_repo 读 id-bearing 历史，不再传 history）
- [x] 3.4 读侧 `get_summary_hint(session_id) -> str`：纯读缓存、不调 LLM；无摘要返回空串
- [x] 3.5 缓存命中/失效：`covered_upto` = 末条已压缩 turn id；id 之后的窗外新回合滚动并入，id 对不上即全量重算
- [x] 3.6 容错降级：`summarize` 失败/超时时 `compact_if_needed` 捕获、不写缓存、记 `degraded`，不抛异常（读侧自然退回纯窗口）
- [x] 3.7 可观测：写侧压缩经 `tracer` 记录 trigger_reason / tokens_before / tokens_after / latency / degraded
- [x] 3.8 漂移纠偏开关 `full_recompute_after_turns`（默认关/设很大）：覆盖回合数达上限触发一次全量重算

## 4. 编排接入（读/写分处请求两端 — D7）

- [x] 4.1 `api/chat_handler.py` 实例化生产级 `SummaryMemory`（注入 summaries repo + llm + tracer）
- [x] 4.2 读侧：取短期窗口时调 `get_summary_hint(sid)`，非空时包成独立 `SystemMessage` 置于 `history` 首条（系统提示之后、短期窗口之前；与 `system_suffix` 区分）
- [x] 4.3 写侧：在回写 assistant 回复之后、`ProcessUserInput_stream` 生成器返回前，**inline-after-stream** 同步调 `compact_if_needed(...)`（不用 fire-and-forget）
- [x] 4.4 并发兜底确认：下一轮启动时摘要未就绪 → 读侧取空 → 退回纯窗口，不阻塞

## 5. 机制单元测试（fake LLM，确定性、不触网 — D9）

- [x] 5.1 未超阈值不触发：`compact_if_needed` 不调用 LLM、不写缓存（fake LLM 断言零调用）
- [x] 5.2 超阈值触发：窗外回合被压缩、写入缓存；读侧能取回并注入为 history 首条 SystemMessage
- [x] 5.3 滚动压缩：存在前序摘要时 `summarize` 收到「前序摘要 + 新出窗回合」，非全量重算
- [x] 5.4 缓存命中：`covered_upto` 未变时 `compact_if_needed` 不重复调 LLM
- [x] 5.5 降级路径：fake LLM 抛异常/超时 → 不崩、不写缓存、记 degraded、读侧退回空摘要
- [x] 5.6 可观测：断言 tracer 收到压缩 event 及关键属性
- [x] 5.7 写侧时机：断言压缩发生在 assistant 回复回写之后、生成器结束之前

## 6. 评估与验证（独立 evals — D9）

- [x] 6.1 在 `evals/` 增补长会话对照用例（真 LLM）：早期约束滑出窗口后，后续轮次仍遵守（压缩生效）；不进 pytest 主回归（`evals/eval_compaction.py`）
- [x] 6.2 跑 `uv run pytest` 全绿（含既有 session-memory 回归）→ 156 passed, 9 xfailed
- [x] 6.3 单独跑 `evals/` 长会话用例对照基线无回归 → 真 LLM 跑通，女技师/周末/预算约束经单次+滚动压缩均保留
- [x] 6.4 更新 `docs/harness-refactor-plan.md` Phase 4 备注：compaction 由 stub 升级为生产实现，标注触发/降级/读写分离策略
