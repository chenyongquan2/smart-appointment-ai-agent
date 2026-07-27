# 任务清单：飞书 Channel + 任务执行层

## 1. 任务执行层（executor/）

- [ ] 1.1 定义任务模型与接口：`Task`（session_id, input, channel 元数据）、`TaskExecutor.submit() → TaskHandle`、`TaskHandle.stream()/result()`、终态枚举（成功/失败/超时/guardrail 耗尽）
- [ ] 1.2 实现进程内 asyncio executor：每 session 一条队列（同话题串行）、全局 Semaphore 并发上限（默认 10，可配）、墙钟超时 `asyncio.wait_for`（默认 600s，可配）
- [ ] 1.3 接入 harness：worker 按任务拉起 AgentLoop（复用 `api/chat_handler` 现有装配逻辑），guardrail 耗尽映射为失败终态
- [ ] 1.4 单测（注入 fake 慢任务/抛错任务）：同话题串行、跨话题并行、并发上限排队、墙钟超时终态、四种终态回调各一条

## 2. Web 接线切换（对外行为不变）

- [ ] 2.1 `web/routes.py`/`api/chat_handler.py` 改走 executor 同步特例（`TaskHandle.stream()` 透传流式），加环境变量开关保留旧直调路径可回滚
- [ ] 2.2 验证：`uv run pytest` 全绿 + `evals/` 门禁通过（退出码 0），确认 Web 对外行为无变化

## 3. 飞书接入层（channels/lark/）

- [ ] 3.1 引入 `lark-oapi` 依赖（uv add），`.env` 增加 app_id/app_secret/domain/并发/超时配置项与 `.env.example` 说明（含所需 im 权限 scope 清单）
- [ ] 3.2 DB 新增 channel_session 映射表（channel, thread_id, session_id, created_at）与 Repository，session_id 命名 `feishu:{thread_id}`
- [ ] 3.3 实现 gateway：事件解析（仅处理 @bot 文本消息）、event_id 内存 TTL 去重、thread→session 解析、秒回 ack 后 submit 任务
- [ ] 3.4 实现 delivery：终态回调统一出口，结果/失败/超时文案投递回原话题，投递失败重试 2 次 + 结构化错误日志（绝不静默）
- [ ] 3.5 实现 consumer：lark-oapi 长连接订阅 `im.message.receive_v1`，连接状态结构化日志，启动时权限自检并明确报错
- [ ] 3.6 单测（fake 飞书 client）：@判定与忽略、event 去重幂等、同话题共享会话/跨话题隔离、ack 先于结果、四种终态均有投递、投递失败重试

## 4. 端到端验证与收尾

- [ ] 4.1 用真实飞书租户凭据在测试群端到端验证：@bot 多轮对话、话题隔离、长任务先 ack 后结果、超时兜底回复
- [ ] 4.2 全量验证：`uv run pytest` 全绿 + evals 门禁通过；RUNNING.md 补充飞书接入的配置与启动说明
