## 1. 持久化层（DB）

- [x] 1.1 在 `db/models.py` 新增 `ConversationTurn` 模型（`id` PK、`session_id` String 索引、`role` String、`content` Text、`created_at` DateTime 默认 utcnow）
- [x] 1.2 新增 `db/repositories/conversation_repository.py`：`ConversationRepository(session_manager)`，提供 `append_turn(session_id, role, content) -> int` 与 `get_turns(session_id, limit=None) -> list[dict]`（经 `session_scope`，风格对齐 `UserBehaviorRepository`，含 `_turn_to_dict`）
- [x] 1.3 在 `db/repositories/__init__.py` 导出 `ConversationRepository`；在 `db/db_router.py` 的 `DatabaseRouter` 实例化并加 `conversations` property
- [x] 1.4 为 `ConversationRepository` 写单测（用临时/内存 SQLite）：append 后 get 能读回、按 session 隔离、limit 取最近 N 条

## 2. 会话状态与记忆（harness）

- [x] 2.1 新增 `harness/runtime/session.py`：`Turn` dataclass（role/content）、`SessionState` dataclass（session_id/history/user_id）、`SessionStore`（`get_or_create(session_id)`，miss 时经 `ConversationRepository` 懒加载历史；`append_turn` 写内存+DB）
- [x] 2.2 新增 `harness/memory/__init__.py` 与 `harness/memory/short_term.py`：`ShortTermMemory(window_turns=10)`，输入 `list[Turn]` 输出最近 N 轮的 `list[BaseMessage]`（user→HumanMessage、assistant→AIMessage）
- [x] 2.3 新增 `harness/memory/long_term.py`：`LongTermMemory(repo)`，`build_preference_hint(user_id) -> str` 读 `repo.get_user_preferences`，组装中文偏好提示；空/异常返回空串
- [x] 2.4 新增 `harness/memory/summary.py`：`SummaryMemory` Protocol（`summarize(old_turns) -> str`）+ 占位 `NoOpSummary`；docstring 写明触发条件（`len(history) > window_turns` 本应压缩），本 Phase 不压缩
- [x] 2.5 为 `ShortTermMemory`（窗口裁剪、超窗只取最近 N）与 `LongTermMemory`（有偏好/无偏好）写单测

## 3. Agent Loop 注入历史

- [x] 3.1 修改 `harness/runtime/agent_loop.py`：`run(user_input, session_id=None, history=None)`，把 `history`（已裁剪的 `list[BaseMessage]`）插入 system prompt 之后、当前 user message 之前
- [x] 3.2 确保最终 `[REPLY]`（含 max_steps 兜底回复）的文本可被调用方捕获以回写历史（不改 yield 前缀协议）
- [x] 3.3 更新/新增 `AgentLoop` 单测：带 history 时上下文包含历史消息；不带 history 时与原行为一致（用 fake LLM，离线确定性）

## 4. 编排入口与 Channel 层

- [x] 4.1 重写 `api/chat_handler.py`：移除全局 `global_session_id` 与单例耦合；构造 `SessionStore`/`ShortTermMemory`/`LongTermMemory`；`ProcessUserInput_stream(user_input, session_id=None, ...)` 按 session 取状态、注入短期历史 + 长期偏好提示、驱动 loop、回写本轮历史；缺省 `session_id` 时生成并可回传
- [x] 4.2 修改 `web/routes.py`：`ChatRequest` 新增 `session_id: str | None`；`/chat/stream` 与 `/chat` 透传 `session_id`，并在响应头 `X-Session-Id` 回传服务端采用的 id
- [x] 4.3 写端到端测试：同一 `session_id` 两轮对话注入上文；两个不同 `session_id` 并发互不串号

## 5. 持久化恢复与验收

- [x] 5.1 写重启恢复测试：写入若干回合后新建 `SessionStore`（模拟重启），按同一 `session_id` 能从 DB 恢复历史
- [x] 5.2 跑 `uv run pytest`，全绿（成功静默、只报失败）
- [x] 5.3 跑 `evals/`（`uv run python evals/run_evals.py` 或既有运行器），不低于基线
- [x] 5.4 核对验收标准：两 session 并发互不干扰 ✓、重启后恢复会话 ✓、测试与评估全绿 ✓
