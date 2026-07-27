# 设计：飞书 Channel + 任务执行层

## Context

当前唯一入口是 Web（`web/routes.py` → `api/chat_handler.ProcessUserInput_stream`，同步流式）。飞书是事件驱动 + 异步长任务：必须秒回 ack、结果稍后投递回话题。harness 运行时（`AgentLoop`）无状态、按 session 隔离，天然支持"按任务拉起"，但 Channel 与 Agent 之间缺一个任务式接口层。

参考系统：`C:\workspace\lark-oncall-bot`（生产级 Lark 值守 bot）已趟平 Lark 接入的坑（长连接订阅、bot/user 双身份、超时看门狗、绝不静默），其设计教训直接复用。

## Goals / Non-Goals

**Goals:**
- 飞书群 @bot 可与现有预约 Agent 对话（多轮、话题隔离）
- Channel↔Agent 之间建立任务式接口；Web 改为其同步特例，对外行为不变
- 现有 pytest + evals 门禁全绿，且新增能真正覆盖改道路径的回归测试

**Non-Goals:**
- oncall 工具集与领域包化（下一个 change）
- 飞书消息的流式编辑（结果一次性投递即可）
- 跨进程/分布式任务队列（单实例进程内实现，接口留好抽象）
- 危险工具的幂等键（超时后副作用不一致只用文案兜住，根治另开）
- Lark 国际租户实测（域名可配即可，本次只验飞书）

## Decisions

### D1 飞书接入用 `lark-oapi` 官方 Python SDK 的长连接模式，不用 lark-cli 子进程

- 理由：进程内 websocket 客户端 + 事件回调，无公网回调地址要求；避免引入 Node 依赖、子进程管理和 NDJSON tail（lark-oncall-bot 用 lark-cli 是因为它零 pip 依赖的约束，本项目没有这个约束）。
- 备选：lark-cli 子进程（成熟先例，但多一层进程管理）；HTTP 回调模式（需要公网地址，排除）。
- SDK 断线自动重连由其内置机制承担，接入层记录连接状态结构化日志。

### D2 executor 为进程内 asyncio 实现，且提供两种执行模式

- **两种模式**：`submit(task, on_complete) → task_id`（IM 用，入队 + worker 协程执行 + 终态回调）与 `execute_inline(task)`（Web 用，在调用方协程内直接跑并透传 generator）。二者共享同一个全局 `Semaphore`（默认 10）与同一把 per-session 锁，故"同话题串行 / 跨话题并行 / 并发上限"对两条路径同等生效。
- **为什么 Web 不走队列**：把 Web 改成"worker 协程产 token → 队列 → 请求协程消费"会凭空引入三个当前不存在的问题——背压（无界队列会涨、有界会卡 worker）、断连语义（浏览器关页面时 worker 是跑完还是被 cancel，直接影响 assistant 回合是否落库）、异常跨协程重抛。而本变更的硬要求恰恰是 Web 行为不变。inline 模式下透传的还是同一个 async generator，"行为不变"在构造上成立，不需要测出来。
- **抽象没有被破坏**：`execute_inline` 也是接口的一部分。将来 executor 拆独立服务时，inline 本就要退化成 `submit` + SSE——届时改的是那时真正需要的东西，而不是现在为不确定的未来预付成本。
- **不引入 TaskHandle**：飞书只需要终态回调，Web 直接拿 generator，没有第三方需要句柄。少一个概念。
- **`[REPLY]` 协议归 executor**：结构化终态 `{status, reply_text, error}`，从 token 流择出最终回复由 executor 的 worker 承担——这段逻辑本就存在于 `api/chat_handler.py`，是平移而非新增耦合。Channel 只读字段，与"Channel 换掉、Agent 不改"的分层判据一致。
- 备选：Celery/RQ——单实例场景纯属过度设计，违反项目 KISS 准则。
- **留给后续**：更彻底的做法是让 `AgentLoop` 产出结构化事件而非 `[THOUGHT]`/`[REPLY]` 字符串前缀（更贴合项目"结构化输出 > 字符串解析"准则），但会波及 `evals/agent_capture.py`、Web 前端解析与 evals 基线。本期不做，留到领域包化那期一并处理。

### D3 超时分三层，各层归属明确，不重复造看门狗

| 层 | 归属 | 默认 | 超时后 |
|---|---|---|---|
| 任务墙钟总超时 | executor（本 change 新增） | 600s | 终止任务，回调超时终态 |
| 单次工具调用 | `Tool.timeout` + `agent_loop._dispatch`（本 change 补齐） | 60s（`delegate` 豁免） | 当错误结果回灌，**不重试** |
| 单次 LLM 请求 | `guardrails.guarded_invoke`（**已实现，不动**） | 30s / 3 次 | 指数退避重试；耗尽 → 失败终态 |

- LLM 侧的超时与重试**已经存在**（`harness/guardrails/retry.py:guarded_invoke`），本 change MUST NOT 重复实现，只负责把 `GuardrailExhausted` 映射为失败终态。
- 真正的缺口是工具层：`_dispatch` 当前只捕获异常、无超时。现有本地 DB/RAG 工具够快掩盖了它，但第 3 期接 VictoriaLogs / git 等网络工具后是真实挂死风险，故在本 change 一并补齐。
- **超时值声明在工具上，不是全局常量**：`Tool` 增加可选 `timeout` 字段（默认 `None` → 取全局缺省 60s）。必须如此的直接原因是 `delegate`——主 Agent 的 registry 里只注册了它一个工具（`api/chat_handler.py`），而它的 handler 内部跑的是一整个子 AgentLoop（最多 8 步，每步 LLM 最多 30s×3 次重试）。全局 60s 会随机截断正常任务，是误杀不是保护。故 `delegate` 显式豁免。副作用是好的：第 3 期加 oncall 网络工具时，超时成了工具声明处的自然填空，不用回头改运行时。
- **超时只对可中断的工具生效**：`asyncio.wait_for` 无法中断同步阻塞调用。现有工具 handler 签名虽是 async，底下打的若是同步 SQLite / FAISS，到点也 cancel 不掉，会一直占着事件循环。这条边界必须写进工具编写约定——否则第 3 期移植 `repokit.py` 的 git 子进程调用时，会以为有超时保护而其实没有。需要真超时的同步工具自行下沉线程池。
- 工具超时**刻意不重试**，沿用 `_dispatch` 既有的不对称理由：工具可能有副作用（写库下单），重试等于重复执行。

### D4 会话键解析成优先级链，事件去重用内存 TTL

- **不能假设消息带 `thread_id`**：它只在开启话题模式的群中下发；普通群内 @bot 的消息只有 `chat_id` / `message_id` / 回复链的 `root_id`。故会话键解析为 `thread_id → root_id → message_id` 取首个非空，配 `FEISHU_SESSION_SCOPE`（`thread` 默认 / `chat` 整群一条）。默认语义 = "一次 @bot 开一条会话，在该消息下回复继续多轮"，避免整群成员共用一条历史互相串味。
- 映射表持久化（复用现有 SQLAlchemy，新增 `channel_session` 表：`channel / scope / external_id / session_id / created_at`，`(channel, external_id)` 唯一索引），存的是**解析后**的键，进程重启不丢会话。
- **⚠ 待真租户验证**：上述字段可用性是基于飞书 API 的判断，不是实测结论。实施顺序上 MUST 先用一条真实消息把事件载荷打出来确认，再动建表——表一旦写入数据，改键定义就要迁移。
- event_id 去重用内存 TTL 集合（默认 5 分钟 + 容量上限 LRU）。**理由是防重复副作用而非性能权衡**：`create_appointment` 没有幂等键，重复消费一次事件就是真的多下一单，去重是本期唯一的防线。进程重启后的极小概率重复，显式记账为残余风险。

### D5 双层 ack + delivery 统一收口，绝不静默

- **两种 ack 不是一回事，文档里必须分开写**：协议 ack（SDK 事件回调立即返回，绝不 await 任务结果）与用户可见 ack（对触发消息 reply 一条"处理中"）。用 reply 而非表情回应，因为它顺带建立了 D4 会话键所依赖的回复链。顺序：submit → 发用户 ack → 回调返回；用户 ack 投递失败只记日志，不影响任务。
- 任务的所有终态（成功/失败/超时/guardrail 耗尽/忙碌拒绝）都经同一 `delivery` 出口投递到原会话；投递失败重试 2 次，仍失败记结构化错误日志。
- Channel 层不解析 Agent 输出，只读结构化终态字段——与"Channel 换掉、Agent 不改"的分层判据一致。

### D6 测试策略：全部注入 fake，离线确定性

- fake 飞书 client（录制事件回放 + 捕获投递调用）测 channel；fake 慢任务/抛错任务测 executor 的串行、并发、排队上限、超时、终态回调。
- Web 改道的证据靠新增的 HTTP 端到端回归测试（见"验证覆盖边界"），不靠 evals。
- 不新增触网测试。

### D7 飞书长连接跑在 FastAPI 同进程内，硬约束单 worker

- 长连接 consumer 在 FastAPI lifespan 启动，`FEISHU_ENABLED` 开关默认 false。
- **为什么同进程**：executor、`SessionStore` 内存缓存、`_agent_loop` 都是模块级单例（`api/chat_handler.py`）。拆独立进程会立刻引入两份内存会话缓存不一致，以及 SQLite 多进程写锁竞争。同进程则天然单写者。
- **硬约束**：MUST 以单 worker 运行（`uvicorn --workers 1`，默认即是）。多 worker 会起多份长连接、重复消费同一事件——而去重表是进程内的，拦不住跨进程重复。
- 开发态 `--reload` 会在热重启时重连，建议开发时关掉飞书开关。

### D8 非成功终态补写兜底 assistant 回合

- `api/chat_handler.py` 的顺序是：写 user 回合 → 驱动 loop → 写 assistant 回合。任务在中途被 cancel（墙钟超时）会在库里留下永远配不上回复的孤立 user 回合。
- 后果按严重度递增：① 下一轮模型看到一句没人回的话，用户重问后历史里出现连排的重复 user 消息；② `_summary.compact_if_needed` 在 cancel 路径上被跳过一轮（幂等、下次能补，但需确认容忍缺口）；③ cancel 落在 `create_appointment` 已写库之后——预约真建了，用户收到的是"超时"。
- 决策：失败/超时/guardrail 耗尽三种终态都补写一条与投递文案一致的 assistant 回合。`ProcessUserInput_stream` 捕 `CancelledError` → 补写 → **重新抛出**（吞掉会让 executor 误判成功）。
- 第 ③ 类副作用不一致本期只用文案兜住（"若已产生预约请勿重复操作"）+ 绝不自动重试；根治要给危险工具做幂等键，属另一期。

### D9 单会话排队深度上限

同话题串行下，用户连发 5 条就排 5 个任务、最终投 5 条回复——刷屏且白烧 token，被刷时队列还会无界堆积。故每 session 排队深度上限默认 5，超出直接以"忙碌"终态回调、不入队。原 spec 只有全局并发上限，缺这条。

## 验证覆盖边界

**`evals/` 证明不了 Web 改道无回归。** `evals/agent_capture.py` 直接构造 `AgentLoop`，完全不经过 `api/chat_handler`、`web/routes` 与 executor。因此：

- "evals 门禁绿 ⇒ Web 行为无变化"是**无效推理**。
- 更危险的是改道前后跑 evals 做 A/B 比对：两次跑的是同一条不受改动影响的路径，数字必然一致，得到的"无回归"是假阳性安慰。

各自的有效范围：

| 证据 | 能证明什么 | 不能证明什么 |
|---|---|---|
| `evals/` 门禁 | D3 的工具超时改动没有伤到 `AgentLoop` 及其下层 | 任何 web / executor 接线的正确性 |
| 新增 HTTP 端到端回归测试 | Web 改道后对外行为不变 | Agent 决策质量 |
| executor / channel 的 fake 单测 | 串行、并发、排队、超时、终态回调、去重、投递重试 | 真实飞书租户的字段与权限行为 |
| 真租户手工验证 | 事件载荷字段、权限 scope、端到端可用 | 回归（不可重复执行） |

新增的 HTTP 端到端回归测试用 `starlette.TestClient` 打 `/chat/stream`，LLM 注入 fake（复用 `tests/test_chat_handler_e2e.py` 的模块级单例 monkeypatch 手法，离线确定性），断言：token 序列、`X-Session-Id` 响应头、多轮上下文接续、跨 session 不串号。`httpx` 当前只是传递依赖，需显式加入 dev 依赖组。

## Risks / Trade-offs

- [进程 crash 时队列中任务丢失，用户收不到回复] → 初期接受（重启后用户重问即可），记录启动时告警日志；任务表持久化列入后续演进。
- [长连接静默断开] → 依赖 SDK 自动重连 + 连接状态日志；后续可加心跳自检。
- [飞书应用权限不足（读消息/发消息 scope 缺失）] → 前置条件文档写清所需 scope 清单，接入层启动时自检并明确报错。
- [同话题串行导致用户连发消息排队] → 符合预期（回复乱序更糟）；ack 让用户知道已收到；超出排队上限时明确拒绝（D9）。
- [会话键定义依赖未实测的飞书字段] → 实施上强制"先打真实事件载荷、后建表"（D4）；判断有误时需迁移映射表。
- [SQLite 并发写锁] → 10 个并发任务同时 `append_turn` 有 `database is locked` 风险。本期不改 DB；实施端到端验证时确认现有 `db/base/session_manager.py` 是否已开 WAL，真出现问题先开 WAL（一行配置）。
- [超时后副作用不一致] → 已下单却回超时。本期文案兜底 + 绝不自动重试；根治需幂等键（D8）。
- [进程重启后事件去重表清空] → 极小概率重复消费导致重复下单，显式记账（D4）。
- [`submit` 路径不被 Web 流量覆盖] → 两模式的代价：worker 路径的质量只能靠 fake 单测保证，而不是"Web 天天在跑所以没问题"。故 executor 单测的覆盖要求写死在 tasks 里。

## Migration Plan

按 commit 顺序分三步，每步全绿再进下一步：
1. `executor/` 落地 + `Tool.timeout` + Web 接线切换（新增 HTTP 端到端回归测试 + 现有 pytest + evals 验证）
2. `channels/lark/` gateway/delivery + DB 映射表（**先真租户打一条事件载荷确认字段**，再建表；fake client 单测）
3. 长连接 consumer 接真飞书租户，群内端到端手工验证

回滚：第 1 步保留旧直调路径的接线开关（`EXECUTOR_ENABLED`，默认 true，应急可切 false）；第 2、3 步为纯新增，回滚即关 `FEISHU_ENABLED`。

## Open Questions

- 飞书应用凭据与 scope 由用户在开放平台创建后提供（app_id/app_secret，开通 im:message 收发权限）
- ack 与超时文案的具体措辞——实现时定，不影响架构（超时文案必须含副作用提示，见 D8）
