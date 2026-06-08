## Context

Phase 3 落地了 TAO 循环，但 [api/chat_handler.py](../../../api/chat_handler.py) 仍用模块级单例 `_agent_loop` + 全局 `global_session_id`，且 `AgentLoop.run()` 每次从零构建 `messages`（[harness/runtime/agent_loop.py:68](../../../harness/runtime/agent_loop.py)）。结果：多用户串号、无多轮记忆。

现有可复用资产：
- `db/base/session_manager.py` 的 `SessionManager`（`session_scope()` 事务上下文）与 `db/models.py` 的 `Base`（SQLAlchemy declarative）。
- `db/db_router.py` 的 `DatabaseRouter` 按 property 暴露各 Repository。
- `db/repositories/user_behavior_repository.py` 的 `get_user_preferences(user_id, ...)`（已返回按 `confidence_score` 排序的偏好），以及 `agents/user_behavior/preference_manager.py`。

约束（黄金准则）：结构化输出>字符串解析；一个概念一个文件；记忆/Repository 是薄封装不重写业务；按 `session_id` 隔离禁止全局串号；不动 `services/`、`db/` 既有 Repository 实现、`config/model_provider.py`、RAG。

## Goals / Non-Goals

**Goals:**
- 按 `session_id` 隔离会话状态，支持并发用户互不干扰。
- `AgentLoop` 注入短期对话窗口（最近 N 轮）并回写历史。
- 复用既有偏好作为长期记忆，跨会话注入系统提示。
- 会话历史持久化到 SQLite，进程重启可恢复。
- 定义摘要层接口与触发条件（留 stub）。

**Non-Goals:**
- 不实现真正的摘要压缩逻辑（只留接口 + 占位实现）。
- 不引入 Redis / 外部存储（沿用 SQLite）。
- 不做用户鉴权 / 多租户 user_id 体系（沿用既有 `default_user` 约定，`user_id` 暂等同会话发起者，可后续细化）。
- 不改 `[THOUGHT]`/`[REPLY]`/`[ERROR]` 前缀协议与前端解析。

## Decisions

### D1. 会话状态用进程内 `SessionStore` + DB 持久化，而非纯 DB 每次读写
`harness/runtime/session.py` 定义 `SessionState`（dataclass：`session_id`、`history: list[Turn]`、可选 `user_id`）与 `SessionStore`（`Dict[str, SessionState]`，`get_or_create(session_id)`）。`SessionStore` 在内存缓存热会话，miss 时从 `ConversationRepository` 懒加载历史；每轮结束写回 DB。
- **理由**：内存 Dict 满足"并发隔离"与低延迟；DB 满足"重启恢复"。这正是 LangGraph checkpointer（`SqliteSaver`）的常见组合。
- **替代**：纯 DB 每请求读写——简单但每轮多次 IO；纯内存——重启即丢，违背验收。

### D2. 短期记忆 = 历史窗口注入，由 `ShortTermMemory` 负责裁剪
`harness/memory/short_term.py` 提供 `ShortTermMemory(window_turns=N)`，输入完整历史、输出最近 N 轮的 `BaseMessage` 列表。`AgentLoop.run()` 把它的输出插在 system prompt 之后、当前 user message 之前。
- **理由**：一个概念一个文件；窗口裁剪与循环编排解耦，便于单测。
- **N 默认值**：取 `window_turns=10`（约 10 轮 = 20 条消息），可在构造时覆盖。

### D3. `AgentLoop.run()` 签名扩展为接收会话历史，回合结束 yield 后回写
`run(user_input, session_id=None, history=None)`：注入 `history`（已裁剪的短期窗口）；循环产出最终 `[REPLY]` 后，把本轮 `(user_input, reply_text)` 作为新 `Turn` 返回给调用方（`chat_handler`）写回 `SessionStore`+DB。
- **理由**：`AgentLoop` 保持无状态（只读 history、产出 reply），状态归属 `SessionStore`，符合单向依赖与可测性。让 loop 自己写 DB 会把持久化耦合进运行时。
- **实现细节**：`run()` 改为同时 yield token 并在结束时暴露最终 reply 文本；用一个轻量累加器在 `chat_handler` 侧捕获 `[REPLY]` 内容回写，避免改 loop 的 yield 协议。

### D4. 长期记忆走只读薄封装 `LongTermMemory`
`harness/memory/long_term.py` 的 `LongTermMemory(repo)` 调 `repo.get_user_preferences(user_id)`，组装成一段中文提示补充（如"该用户偏好：女技师、60 分钟、肩颈"）。由 `chat_handler` 注入到 system prompt 末尾。
- **理由**：复用既有偏好逻辑（黄金准则：薄封装不重写）。读取失败/空偏好返回空串，不影响主流程。

### D5. 摘要层只定义接口 + 占位实现
`harness/memory/summary.py`：`class SummaryMemory(Protocol)` 约定 `summarize(old_turns) -> str`；占位 `NoOpSummary` 在历史超窗口时**不压缩、直接丢弃窗口外旧回合的注入**（旧回合仍持久化在 DB）。docstring 写明触发条件（`len(history) > window_turns` 时本应压缩）。
- **理由**：本项目对话短，摘要收益低、复杂度高（见与用户的范围确认）；先留扩展点。

### D6. 持久化 = 新增 `ConversationTurn` 模型 + `ConversationRepository`
`db/models.py` 新增 `ConversationTurn(id, session_id, role, content, created_at)`（role ∈ user/assistant）。`db/repositories/conversation_repository.py` 提供 `append_turn(session_id, role, content)` 与 `get_turns(session_id, limit=None)`，经 `session_manager.session_scope()` 管理事务，风格对齐 `UserBehaviorRepository`。`DatabaseRouter` 新增 `conversations` property。
- **理由**：复用 `SessionManager`/`Base`，`create_all` 自动建表，无迁移脚本负担；不动既有 Repository。
- **替代**：把历史塞进 `UserBehavior.action_data`——语义混淆，且会污染行为分析数据。

### D7. 请求/响应传递 `session_id`
`web/routes.py` 的 `ChatRequest` 新增 `session_id: str | None`；`/chat/stream` 与 `/chat` 把它传入 `ProcessUserInput_stream`，并在响应中回传服务端最终采用的 `session_id`（通过响应头 `X-Session-Id`，避免污染 token 流）。前端可选改造（最小化：本 Phase 后端回传即可，前端带回留待需要时）。
- **理由**：流式响应体是纯文本 token，用 header 传 `session_id` 不破坏既有前缀解析。

## Risks / Trade-offs

- **内存 Dict 无界增长** → `SessionStore` 仅缓存历史窗口所需，且可加 LRU/容量上限（本 Phase 简单实现，文档标注后续可加淘汰）。
- **`user_id` 与 `session_id` 关系未定** → 本 Phase 沿用 `default_user` 读取偏好，长期记忆按用户而非会话；多用户鉴权留待后续，不阻塞验收。
- **并发写同一 session** → 单进程 asyncio 下回合串行追加，风险低；跨进程一致性非本 Phase 目标（无 Redis）。
- **`run()` 回写最终 reply 的捕获** → 用累加器读取 `[REPLY]` 段，需保证 fallback 回复也被记入历史；测试覆盖。

## Migration Plan

1. 加 `ConversationTurn` 模型（`create_all` 自动建表，旧库自动补表，无破坏）。
2. 加 Repository / memory / session 新文件（纯新增，不影响现有路径）。
3. 改 `chat_handler` 去全局单例、改 `agent_loop.run` 注入历史、改 `routes` 传 `session_id`。
4. 跑 `uv run pytest` + `evals/`。
- **回滚**：Phase 3 的 `chat_handler`/`agent_loop` 可从 git 还原；新增文件与新表不影响旧逻辑。

## Open Questions

- 是否需要前端实际带回 `session_id`（多标签页隔离）？本 Phase 后端先就绪，前端按需接。
- `user_id` 体系何时引入（影响长期记忆精度）？留待 Phase 5/6。
