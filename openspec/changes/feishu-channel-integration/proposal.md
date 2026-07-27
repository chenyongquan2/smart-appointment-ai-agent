# 接入飞书 Channel + 任务执行层

## Why

当前 Agent 只有 Web 端一个入口（FastAPI 请求-响应流式），无法进入团队日常协作的 IM 场景。目标是把现有 harness 暴露到飞书群里（@bot 对话），为后续 oncall 领域包落地铺路。飞书是事件驱动 + 异步长任务模型，与 Web 的同步请求-响应根本不同，因此需要在 Channel 与 Agent 之间引入任务式接口——这是本次变更真正的新架构工作。

## What Changes

- 新增 `channels/lark/` 飞书接入层（飞书/Lark API 同构，先以飞书租户 `open.feishu.cn` 落地，域名可配置）：
  - 长连接事件订阅 `im.message.receive_v1`，事件解析与**去重**（飞书事件可能重复投递，按 event_id 幂等）
  - `thread_id → session_id` 映射（复用现有按 session 隔离的记忆体系，命名空间 `{channel}:{thread_id}`）
  - **秒回 ack**（"收到，正在处理"）后提交任务，不阻塞收件
  - 结果投递回原话题，投递失败兜底（**绝不静默**：任何终态都必须给用户一条回复）
- 新增 `executor/` 任务执行层，Channel 与 Agent 之间从同步调用改为任务式接口：
  - `submit(task) → task_id`，完成后回调 Channel 投递
  - **同一话题严格串行、跨话题并行**（并发上限可配）
  - 墙钟总超时兜底 + LLM 请求级 hang 看门狗（只盯"等模型开口"窗口，工具执行不计入）
- 现有 Web channel 改为任务模型的**同步特例**（提交后原地等结果流式返回），对外行为不变
- `harness/` 运行时与预约领域工具**一行不动**
- 范围**不含** oncall 工具集与领域包化（后续 change）

前置条件：需在飞书开放平台创建应用获取 app_id/app_secret（用户操作）。

## Capabilities

### New Capabilities

- `feishu-channel`: 飞书 IM 接入——长连接事件订阅、事件去重、thread→session 映射、秒回 ack、结果投递与失败兜底
- `task-executor`: Channel 与 Agent 之间的异步任务执行——任务提交/回调接口、同话题串行/跨话题并行、墙钟超时、hang 看门狗

### Modified Capabilities

（无——Web 端对外行为不变，`agent-loop`/`session-memory` 等既有 spec 的需求不变，仅调用方式经由 executor。）

## Impact

- 新增目录：`channels/lark/`、`executor/`
- 修改：`web/routes.py` 与 `api/chat_handler.py` 的接线（改走 executor 的同步特例路径），对外 API 不变
- 新增依赖：飞书官方 SDK（`lark-oapi`，长连接模式）或 lark-cli 子进程二选一（design 中决策）
- 配置：`.env` 新增飞书 app_id/app_secret/domain/并发与超时参数
- 验证：现有 `uv run pytest` 与 `evals/` 门禁必须保持全绿；executor 与 channel 新增单测（注入 fake，离线确定性）
