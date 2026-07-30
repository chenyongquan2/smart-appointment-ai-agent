# 接入飞书 Channel + 任务执行层

## Why

当前 Agent 只有 Web 端一个入口（FastAPI 请求-响应流式），无法进入团队日常协作的 IM 场景。目标是把现有 harness 暴露到飞书群里（@bot 对话），为后续 oncall 领域包落地铺路。飞书是事件驱动 + 异步长任务模型，与 Web 的同步请求-响应根本不同，因此需要在 Channel 与 Agent 之间引入任务式接口——这是本次变更真正的新架构工作。

## What Changes

- 新增 `channels/lark/` 飞书接入层（飞书/Lark API 同构，先以飞书租户 `open.feishu.cn` 落地，域名可配置）：
  - 长连接事件订阅 `im.message.receive_v1`，事件解析与**去重**（按 event_id 幂等；理由是危险工具无幂等键、重复消费等于重复下单）
  - 会话键 → session_id 映射（**`root_id → message_id`**，`thread_id` 不参与取键——实测它只出现在续话消息上、首条没有，排首位会让首条与其回复落到不同会话；复用现有按 session 隔离的记忆体系，命名空间 `feishu:{解析后的键}`）
  - 回复**发进话题**（`reply_in_thread`）+ 结果用交互式卡片渲染 markdown：一问一答连同后续追问收进同一话题，主聊天流只留折叠入口；否则每条机器人消息头上顶一遍原文、且 `**加粗**` 原样显示星号
  - **双层 ack**：事件回调立即返回（协议层）+ 对触发消息 reply 一条"处理中"（用户可见），均不阻塞收件
  - 发送者 open_id 作为 `user_id` 随任务传递，使群内成员的长期偏好按人隔离（历史仍按会话共享）
  - 结果投递回原会话，投递失败兜底（**绝不静默**：任何终态都必须给用户一条回复）
- 新增 `executor/` 任务执行层，Channel 与 Agent 之间从同步调用改为任务式接口：
  - `submit(task, on_complete) → task_id`（IM 用，异步 + 终态回调）与 `execute_inline(task)`（Web 用，同步透传流式），两模式共享同一套并发记账
  - **同一话题严格串行、跨话题并行**（并发上限可配），每会话排队深度上限防刷屏
  - 三层超时各归其位：任务墙钟 600s（本期新增）/ 单次工具 60s（本期补齐，声明在 `Tool` 上，`delegate` 豁免）/ 单次 LLM 30s（`guarded_invoke` **已实现，不重复造**）
  - 非成功终态补写兜底 assistant 回合，保住"历史成对"，避免多轮上下文断档
- 现有 Web channel 改为任务模型的**同步特例**（在请求协程内执行并透传 generator），对外行为不变
- `harness/` 运行时与预约领域工具**一行不动**
- 范围**不含** oncall 工具集与领域包化（后续 change）

前置条件：需在飞书开放平台创建应用获取 app_id/app_secret（用户操作）。

## Capabilities

### New Capabilities

- `feishu-channel`: 飞书 IM 接入——长连接事件订阅、事件去重、会话键解析与映射、双层 ack、用户身份传递、结果投递与失败兜底
- `task-executor`: Channel 与 Agent 之间的任务执行——异步提交/回调与同步内联两种模式、同话题串行/跨话题并行、排队深度上限、墙钟超时、工具调用超时、非成功终态的历史完整性

### Modified Capabilities

- `tool-layer`: 「工具定义结构」新增可选 `timeout` 声明（默认 `None` → 取全局缺省；`delegate` 显式豁免），并写明「超时只能中断有 await 点的 handler，同步阻塞工具须自行下沉线程池」这一适用边界。
- `structured-logging`: 「统一结构化 JSON 日志」新增——`extra={...}` 业务字段必须一并输出、核心字段不被同名键覆盖、不可序列化值降级为字符串而非抛异常。此前 formatter 把 `extra` 全部丢弃，全应用的结构化字段等于白写（本变更实测中因此拿不到会话键诊断信息）。
- `agent-loop`: 「工具失败不崩循环」扩展为覆盖超时——每次工具分发按该工具的 `timeout` 施加上限，超时按同一错误回灌路径喂回且 MUST NOT 重试；同时明确 LLM 侧超时/重试仍归 `guardrails`，不在工具层重复实现。

（`session-memory` 不变：`LongTermMemory` 契约未改，本次只是调用方开始传 `user_id`——该参数 `SessionStore.get_or_create` 早已支持。Web 端对外行为不变。）

## Impact

- 新增目录：`channels/lark/`、`executor/`
- 修改：`web/routes.py` 与 `api/chat_handler.py` 的接线（改走 executor 的同步内联路径），对外 API 不变；`api/chat_handler.py` 另加 `user_id` 透传与取消时的兜底回合补写
- 修改：`harness/tools/base.py`（`Tool` 加 `timeout` 字段）、`harness/runtime/agent_loop.py`（`_dispatch` 按工具施加超时）
- 新增依赖：`lark-oapi`（飞书官方 SDK，长连接模式；见 design D1）；`httpx` 显式加入 dev 依赖组（Web 端到端回归测试用，当前仅为传递依赖）
- 新增 DB 表：`channel_session` 映射表（`channel / scope / external_id / session_id / created_at`）
- 配置：`.env` 新增 `FEISHU_ENABLED` / app_id / app_secret / domain / `FEISHU_SESSION_SCOPE` / `EXECUTOR_ENABLED` / 并发上限 / 排队深度 / 各层超时
- 部署约束：飞书长连接跑在 FastAPI 同进程，MUST 单 worker 运行（见 design D7），RUNNING.md 需写明
- 验证：现有 `uv run pytest` 与 `evals/` 门禁必须保持全绿；**新增 Web 层 HTTP 端到端回归测试**——`evals/` 不经过 `chat_handler`/`web`/executor，不能作为 Web 改道无回归的依据（见 design「验证覆盖边界」）；executor 与 channel 新增单测（注入 fake，离线确定性）
