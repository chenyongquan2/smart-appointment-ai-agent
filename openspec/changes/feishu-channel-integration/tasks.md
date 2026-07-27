# 任务清单：飞书 Channel + 任务执行层

## 1. 任务执行层（executor/）

- [ ] 1.1 定义任务模型与接口：`Task`（session_id, user_id, input, channel 元数据）、`submit(task, on_complete) → task_id`（异步）与 `execute_inline(task)`（同步透传 generator）两种模式、结构化终态 `TaskResult{status, reply_text, error}`（成功/失败/超时/guardrail 耗尽/忙碌拒绝）。不引入 `TaskHandle`
- [ ] 1.2 实现进程内 asyncio executor：每 session 一把锁（同话题串行）+ 每 session 排队深度上限（默认 5，超出以「忙碌」终态回调、不入队）、全局 `Semaphore` 并发上限（默认 10，可配）、墙钟超时 `asyncio.wait_for`（默认 600s，可配）。两种模式共享同一 Semaphore 与同一 per-session 锁
- [ ] 1.3 接入 harness：worker 按任务拉起 AgentLoop（复用 `api/chat_handler` 现有装配逻辑），从 token 流择出 `[REPLY]` 填入 `TaskResult.reply_text`（协议解析归 executor，Channel 不碰），`GuardrailExhausted` 映射为失败终态
- [ ] 1.4 非成功终态补写兜底 assistant 回合：`ProcessUserInput_stream` 捕 `asyncio.CancelledError` → 写入与投递文案一致的 assistant 回合 → **重新抛出**（不得吞掉，否则 executor 误判成功）；失败/guardrail 耗尽终态同样补写。确认 `_summary.compact_if_needed` 被跳过一轮时可容忍
- [ ] 1.5 `Tool` 增加可选 `timeout` 字段（默认 `None` → 取全局缺省 60s，可配），`agent_loop._dispatch` 按 `tool.timeout` 施加超时；超时**不重试**、当错误结果回灌（复用现有「工具执行失败」回灌口径）；**`delegate` 显式豁免**（其 handler 内部是整个子 AgentLoop，全局 60s 会误杀）；LLM 侧不动（`guarded_invoke` 已有）
- [ ] 1.6 在工具编写约定（`openspec/project.md` 或工具基类 docstring）写明超时边界：`asyncio.wait_for` 只能中断有 await 点的工具，同步阻塞工具（同步 SQLite/FAISS/子进程）需自行下沉线程池，否则声明了 timeout 也无效
- [ ] 1.7 `user_id` 透传：`ProcessUserInput_stream` 增加可选 `user_id` 参数，传给 `SessionStore.get_or_create(sid, user_id=...)`（该参数已支持、只是无人传）；缺省仍为 `default_user`，Web 行为不变
- [ ] 1.8 executor 单测（注入 fake 慢任务/抛错任务）：同话题串行、跨话题并行、并发上限排队、排队深度上限拒绝、墙钟超时终态、五种终态回调各一条；工具超时回灌为错误结果且不被重试；`delegate` 不被默认超时截断；取消时兜底回合被写入且 `CancelledError` 继续传播

## 2. Web 接线切换（对外行为不变）

- [ ] 2.1 `web/routes.py`/`api/chat_handler.py` 改走 `execute_inline`（generator 直接透传，不经跨协程队列），加 `EXECUTOR_ENABLED` 环境变量开关（默认 true）保留旧直调路径可回滚
- [ ] 2.2 **新增 Web 层端到端回归测试**（这是改道无回归的唯一有效证据）：`starlette.TestClient` 打 `/chat/stream`，LLM 注入 fake（复用 `tests/test_chat_handler_e2e.py` 的模块级单例 monkeypatch 手法，离线确定性），断言 ① token 序列与改造前一致 ② `X-Session-Id` 响应头 ③ 多轮上下文接续 ④ 并发不同 session 不串号。`httpx` 显式加入 dev 依赖组
- [ ] 2.3 跑 `uv run pytest` 全绿 + `evals/` 门禁通过（退出码 0）。**注意 evals 的有效范围**：`evals/agent_capture.py` 直接构造 `AgentLoop`，不经 `chat_handler`/`web`/executor，故它证明的是「1.5 的工具超时改动没伤到 AgentLoop」，**不能**作为 Web 改道无回归的依据（详见 design「验证覆盖边界」）

## 3. 飞书接入层（channels/lark/）

- [ ] 3.1 引入 `lark-oapi` 依赖（uv add），`.env` 增加 app_id/app_secret/domain/`FEISHU_ENABLED`/`FEISHU_SESSION_SCOPE`/并发与超时配置项，`.env.example` 补说明（含所需 im 权限 scope 清单）
- [ ] 3.2 **先验证再建表**：拿到凭据后在测试群发一条真实 @bot 消息，把事件载荷 JSON 打出来，确认 `thread_id` / `root_id` / `message_id` / `chat_id` / 发送者 open_id 的实际下发情况。此步 MUST 先于 3.3 完成——表一旦写入数据，会话键定义变更就要迁移
- [ ] 3.3 DB 新增 `channel_session` 映射表（`channel / scope / external_id / session_id / created_at`，`(channel, external_id)` 唯一索引）与 Repository；会话键按 `thread_id → root_id → message_id` 优先级链解析（依 3.2 实测校正），session_id 命名 `feishu:{解析后的键}`
- [ ] 3.4 实现 gateway：事件解析（仅处理 @bot 文本消息）、event_id 内存 TTL 去重（默认 5 分钟 + 容量上限 LRU；**理由是防重复下单，不是性能优化**）、会话键解析、取发送者 open_id 作 user_id、提交任务 → 发用户可见 ack（reply 而非表情，顺带建立回复链）→ 事件回调立即返回（不 await 任务）
- [ ] 3.5 实现 delivery：终态回调统一出口，成功/失败/超时/guardrail 耗尽/忙碌拒绝五种终态文案投递回原会话，投递失败重试 2 次 + 结构化错误日志（绝不静默）；超时文案含副作用提示（「若已产生预约请勿重复操作」），且系统不自动重试
- [ ] 3.6 实现 consumer：lark-oapi 长连接订阅 `im.message.receive_v1`，在 FastAPI lifespan 启动、受 `FEISHU_ENABLED` 控制（默认 false），连接状态结构化日志，启动时权限自检并明确报错
- [ ] 3.7 channel 单测（fake 飞书 client）：@判定与忽略、event 去重幂等、去重表 TTL/容量不无界、会话键解析优先级链（含无 `thread_id` 的回退）、同会话共享/跨会话隔离、user_id 随任务传递、协议 ack 不阻塞、用户 ack 先于结果、五种终态均有投递、投递失败重试

## 4. 端到端验证与收尾

- [ ] 4.1 用真实飞书租户凭据在测试群端到端验证：@bot 多轮对话、会话隔离、长任务先 ack 后结果、超时兜底回复、排队上限提示；确认 `db/base/session_manager.py` 是否已开 WAL（10 并发写 SQLite 的 locked 风险，真出现则开 WAL）
- [ ] 4.2 全量验证：`uv run pytest` 全绿 + evals 门禁通过；RUNNING.md 补充飞书接入的配置与启动说明，**明写 MUST 单 worker 运行**（`uvicorn --workers 1`，多 worker 会起多份长连接重复消费，进程内去重表拦不住），开发态 `--reload` 建议关掉飞书开关
