# 设计：飞书 Channel + 任务执行层

## Context

当前唯一入口是 Web（`web/routes.py` → `api/chat_handler.ProcessUserInput_stream`，同步流式）。飞书是事件驱动 + 异步长任务：必须秒回 ack、结果稍后投递回话题。harness 运行时（`AgentLoop`）无状态、按 session 隔离，天然支持"按任务拉起"，但 Channel 与 Agent 之间缺一个任务式接口层。

参考系统：`C:\workspace\lark-oncall-bot`（生产级 Lark 值守 bot）已趟平 Lark 接入的坑（长连接订阅、bot/user 双身份、超时看门狗、绝不静默），其设计教训直接复用。

## Goals / Non-Goals

**Goals:**
- 飞书群 @bot 可与现有预约 Agent 对话（多轮、话题隔离）
- Channel↔Agent 之间建立任务式接口；Web 改为其同步特例，对外行为不变
- 现有 pytest + evals 门禁全绿

**Non-Goals:**
- oncall 工具集与领域包化（下一个 change）
- 飞书消息的流式编辑（结果一次性投递即可）
- 跨进程/分布式任务队列（单实例进程内实现，接口留好抽象）
- Lark 国际租户实测（域名可配即可，本次只验飞书）

## Decisions

### D1 飞书接入用 `lark-oapi` 官方 Python SDK 的长连接模式，不用 lark-cli 子进程

- 理由：进程内 websocket 客户端 + 事件回调，无公网回调地址要求；避免引入 Node 依赖、子进程管理和 NDJSON tail（lark-oncall-bot 用 lark-cli 是因为它零 pip 依赖的约束，本项目没有这个约束）。
- 备选：lark-cli 子进程（成熟先例，但多一层进程管理）；HTTP 回调模式（需要公网地址，排除）。
- SDK 断线自动重连由其内置机制承担，接入层记录连接状态结构化日志。

### D2 executor 为进程内 asyncio 实现，不引入 Celery/Redis

- 每个 session_id 一条 `asyncio.Queue`（保证同话题串行），全局 `Semaphore(N)` 控并发（默认 10）。
- 接口抽象为 `TaskExecutor.submit(task) → TaskHandle`；`TaskHandle.stream()`（Web 流式消费）与 `TaskHandle.result()`（终态一次取回，飞书用）。将来要跨进程时只换实现不换接口。
- 备选：Celery/RQ——单实例场景纯属过度设计，违反项目 KISS 准则。

### D3 超时分两层，hang 检测复用现有护栏

- executor 只负责墙钟总超时（默认 600s，`asyncio.wait_for`），到点终止任务并回调超时终态。
- LLM 请求级 hang/重试沿用 `harness/guardrails` 现有的超时 + 指数退避护栏（已实现），executor 将 guardrail 耗尽映射为失败终态。不重复造看门狗。

### D4 thread→session 映射落 DB，事件去重用内存 TTL

- 映射表持久化（复用现有 SQLAlchemy，新增一张 channel_session 表：channel, thread_id, session_id, created_at），进程重启不丢会话。
- event_id 去重用内存 TTL 集合（飞书重投窗口短）；进程重启后的极小概率重复以 ack 幂等接受。权衡：写 DB 去重收益低于成本。

### D5 绝不静默由 delivery 统一收口

- 任务四种终态（成功/失败/超时/guardrail 耗尽）都经同一 `delivery` 出口投递到原话题；投递失败重试 2 次，仍失败记结构化错误日志。
- Channel 层不解析 Agent 输出，只透传文本——与"Channel 换掉、Agent 不改"的分层判据一致。

### D6 测试策略：全部注入 fake，离线确定性

- fake 飞书 client（录制事件回放 + 捕获投递调用）测 channel；fake 慢任务/抛错任务测 executor 的串行、并发、超时、终态回调。
- 不新增触网测试；现有 evals 门禁作为 Web 路径无回归的证据。

## Risks / Trade-offs

- [进程 crash 时队列中任务丢失，用户收不到回复] → 初期接受（重启后用户重问即可），记录启动时告警日志；任务表持久化列入后续演进。
- [长连接静默断开] → 依赖 SDK 自动重连 + 连接状态日志；后续可加心跳自检。
- [飞书应用权限不足（读消息/发消息 scope 缺失）] → 前置条件文档写清所需 scope 清单，接入层启动时自检并明确报错。
- [同话题串行导致用户连发消息排队] → 符合预期（回复乱序更糟）；ack 让用户知道已收到。

## Migration Plan

按 commit 顺序分三步，每步全绿再进下一步：
1. `executor/` 落地 + Web 接线切换（对外行为不变，pytest + evals 验证）
2. `channels/lark/` gateway/delivery + DB 映射表（fake client 单测）
3. 长连接 consumer 接真飞书租户，群内端到端手工验证

回滚：第 1 步保留旧直调路径的接线开关（环境变量），验证期可一键切回；第 2、3 步为纯新增，回滚即停用。

## Open Questions

- 飞书应用凭据与 scope 由用户在开放平台创建后提供（app_id/app_secret，开通 im:message 收发权限）
- ack 文案与是否附使用说明（首次交互时）——实现时定，不影响架构
