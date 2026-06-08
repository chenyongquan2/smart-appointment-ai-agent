## Why

当前 harness 用一个模块级单例 `AgentLoop` + 全局 `global_session_id`（[api/chat_handler.py:17](../../../api/chat_handler.py)）服务所有请求：多个用户会**串号**，且每次请求 `messages` 从零构建（[agent_loop.py:68](../../../harness/runtime/agent_loop.py)），**没有多轮记忆**。这是 Phase 4 要解决的"状态与记忆"问题——让 harness 支持并发用户、多轮对话与跨会话偏好。

## What Changes

- **会话隔离**：用 `SessionStore`（按 `session_id` 隔离的 `Dict[str, SessionState]`）取代全局单例状态。`/chat/stream` 与 `/chat` 请求体新增可选 `session_id`；缺省时由服务端生成并随首个响应回传，前端后续请求带回。
- **短期记忆**：`AgentLoop.run()` 接收会话的历史消息并注入到 `messages`，循环结束后把本轮 user/assistant 回合追加回会话历史（保留最近 N 轮窗口）。
- **长期记忆**：通过薄封装 `LongTermMemory` 复用既有 `UserBehaviorRepository.get_user_preferences`，把高置信度偏好作为系统提示补充注入（**不重写**偏好业务逻辑）。
- **摘要层（stub）**：定义 `SummaryMemory` 接口与触发条件（历史超过窗口阈值时压缩），本 Phase **只留接口与 no-op/截断实现**，压缩逻辑留待后续 Phase。
- **持久化**：新增 `ConversationTurn` 模型与 `ConversationRepository`（复用现有 SQLite + SQLAlchemy 与 `SessionManager`），会话历史落库，进程重启后可恢复。
- `ProcessUserInput_stream` 接收 `session_id`，真正驱动按会话隔离的记忆，而非忽略 `state`/`context`。

## Capabilities

### New Capabilities
- `session-memory`: 按 `session_id` 隔离的会话状态与分层记忆（短期对话窗口、长期偏好接入、摘要层接口），含 SQLite 持久化与重启恢复。

### Modified Capabilities
- `agent-loop`: `run()` 从"每次从零构建 messages"改为"接收并注入会话历史、按 session 隔离、回合结束回写历史"。

## Impact

- **修改**：`api/chat_handler.py`（去全局单例，按 session 取/建状态）、`harness/runtime/agent_loop.py`（注入历史 + 回写）、`web/routes.py`（请求/响应带 `session_id`）、`db/models.py`（新增 `ConversationTurn`）、`db/db_router.py`（暴露 `conversations`）。
- **新增**：`harness/runtime/session.py`、`harness/memory/{__init__,short_term,summary,long_term}.py`、`db/repositories/conversation_repository.py`、对应测试。
- **不动（保留资产）**：`services/`、`db/` 既有 Repository 实现、`config/model_provider.py`、RAG（FAISS+SQLite）。`UserBehaviorRepository` 仅被读取，不修改。
- **依赖**：无新增第三方依赖（沿用 SQLAlchemy/SQLite）。
