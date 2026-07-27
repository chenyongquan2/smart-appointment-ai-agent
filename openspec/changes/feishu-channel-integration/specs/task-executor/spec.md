# task-executor 规格

## ADDED Requirements

### Requirement: 任务式接口（两种执行模式）

系统 SHALL 提供 Channel 与 Agent 之间的任务接口，含两种执行模式：

- `submit(task, on_complete) → task_id`：任务入队，由 worker 协程异步执行，终态经回调通知提交方（IM Channel 用）。
- `execute_inline(task)`：在调用方协程内直接执行并透传流式输出（Web 同步特例用）。

两种模式 MUST 共享同一套并发记账（同一全局并发信号量 + 同一 per-session 锁），因此「同话题串行 / 跨话题并行 / 并发上限」对两条路径同等生效。Channel MUST NOT 绕过本接口直接调用 AgentLoop。

终态 SHALL 建模为结构化结果 `{status, reply_text, error}`，`status ∈ {成功, 失败, 超时, guardrail 耗尽}`。从 token 流中择出最终回复（`[REPLY]` 约定）SHALL 由 executor 承担，Channel MUST NOT 解析 Agent 的输出字符串。

理由：Web 的流式行为必须逐字节不变，而「worker 协程产 token → 队列 → 请求协程消费」会引入背压、断连语义与异常跨协程传播三个当前不存在的问题。inline 模式让「行为不变」在构造上成立，而非依赖测试证明。接口抽象仍完整保留——将来 executor 拆为独立服务时，inline 退化为 `submit` + SSE 即可。

#### Scenario: 异步提交与回调
- **WHEN** IM Channel 调用 `submit` 提交一个任务
- **THEN** 立即获得 task_id，任务到达终态时回调被调用且携带结构化结果

#### Scenario: 同步内联执行
- **WHEN** Web 调用 `execute_inline` 执行一次聊天
- **THEN** 在调用方协程内产出与改造前一致的 token 流，不经跨协程队列中转

#### Scenario: Channel 不解析输出协议
- **WHEN** 审查 Channel 层代码
- **THEN** 不存在对 `[REPLY]` / `[THOUGHT]` 前缀的解析，Channel 只读取结构化结果的字段

### Requirement: 同话题串行、跨话题并行

同一 session_id 的任务 MUST 按提交顺序串行执行；不同 session_id 的任务 SHALL 并行执行，并发总数 MUST NOT 超过可配置上限（默认 10）。

#### Scenario: 同话题排队
- **WHEN** 同一话题连续提交两个任务
- **THEN** 第二个任务在第一个终态后才开始执行

#### Scenario: 跨话题并行
- **WHEN** 两个不同话题各提交一个任务且并发未达上限
- **THEN** 两个任务同时执行

#### Scenario: 并发上限
- **WHEN** 运行中任务数已达上限时再提交新任务
- **THEN** 新任务排队等待，不被丢弃

### Requirement: 单会话排队深度上限

每个 session 的等待队列 SHALL 有可配置的深度上限（默认 5）；超出上限时新任务 MUST NOT 入队，SHALL 立即以「忙碌」结果回调提交方，由 Channel 告知用户稍后再试。

理由：同话题串行意味着用户连发 N 条消息会排出 N 个任务并最终投递 N 条回复——既刷屏又白烧 token，且无界队列在被刷时会持续堆积。

#### Scenario: 队列已满时拒绝入队
- **WHEN** 某 session 等待队列已达深度上限，该 session 再提交新任务
- **THEN** 该任务不入队，提交方立即收到「忙碌」终态，用户得到一条明确提示

### Requirement: 墙钟超时兜底

每个任务 SHALL 有可配置的墙钟总超时（默认 600 秒）；超时 MUST 终止任务并以超时终态回调，MUST NOT 让任务无限期运行。

#### Scenario: 超时终止
- **WHEN** 任务执行超过墙钟上限
- **THEN** 任务被终止，提交方收到超时终态回调

### Requirement: 非成功终态的会话历史完整性

任务以「失败 / 超时 / guardrail 耗尽」终态结束时，系统 MUST 向会话历史补写一条 assistant 回合，内容与投递给用户的文案一致。取消路径上捕获的 `CancelledError` 在补写完成后 MUST 重新抛出。

理由：现有编排先写 user 回合再驱动 loop、最后才写 assistant 回合（见 `api/chat_handler.py`）。任务在中途被取消会在库里留下一条永远配不上回复的孤立 user 回合，破坏 `ShortTermMemory` 与摘要压缩「历史成对」的隐含前提，并在用户重问后形成连排的重复 user 消息。吞掉 `CancelledError` 则会让 executor 把被取消的任务误判为正常完成。

边界（诚实标注）：若取消发生在有副作用的工具（如 `create_appointment`）执行**之后**、回复生成之前，则业务副作用已发生而用户收到的是超时提示。本变更 MUST NOT 自动重试，SHALL 在超时文案中明示「若已产生预约请勿重复操作」。根治需要为危险工具引入幂等键，不在本变更范围内。

#### Scenario: 超时后历史成对
- **WHEN** 任务因墙钟超时被取消
- **THEN** 会话历史中该轮的 user 回合有一条配对的 assistant 兜底回合，内容与用户收到的超时文案一致

#### Scenario: 取消信号不被吞掉
- **WHEN** 任务在执行中被取消
- **THEN** 补写兜底回合后 `CancelledError` 继续向上传播，executor 判定为超时/取消终态而非成功

### Requirement: 工具调用超时

工具超时 SHALL 声明在工具自身上（`Tool` 的可选 `timeout` 字段，默认值可配、缺省 60 秒），由分发处按该工具的取值施加；超时后 MUST NOT 重试该工具，SHALL 把「工具超时」作为错误结果回灌给模型，由模型下一轮自行补救。

`delegate` 工具 MUST 豁免默认超时（显式声明为不限时或任务墙钟量级）。理由：主 Agent 的 registry 只注册了 `delegate` 一个工具，而它的 handler 内部运行的是一整个子 AgentLoop（多步 LLM 调用，每步最多 30 秒 × 3 次重试）。若按全局默认 60 秒施加，正常任务会被随机截断——这不是保护而是误杀。把超时声明在工具上，也让后续接入 oncall 网络工具时成为自然的填空项，无需回头改运行时。

理由与边界：

- LLM 请求级的超时与重试**已由** `harness/guardrails/retry.py:guarded_invoke` 承担（单次 30 秒、最多 3 次、指数退避），本需求 MUST NOT 重复实现。真正的缺口在 `harness/runtime/agent_loop.py` 的 `_dispatch`——它只捕获异常、**无超时**。
- 超时**只对存在 await 中断点的工具生效**。`asyncio.wait_for` 无法中断同步阻塞调用（如同步 SQLite / FAISS / 子进程），此类工具即使声明了 timeout 也会阻塞事件循环直到自身返回；需要真实超时保护的同步工具 MUST 自行下沉到线程池。此边界 SHALL 在工具编写约定中写明，避免后续移植网络工具时误以为已有保护。
- 「超时不重试」沿用 `_dispatch` 既有的刻意不对称：工具可能有副作用（如写库下单），重试会重复执行，故只做错误隔离、不做重试。

#### Scenario: 工具超时回灌为错误结果
- **WHEN** 某次工具调用耗时超过该工具声明的超时阈值
- **THEN** 该调用被中断，模型收到一条「工具超时」的错误结果，Agent 循环继续而非崩溃

#### Scenario: 超时的工具不被重试
- **WHEN** 某次工具调用因超时被中断
- **THEN** 该工具 MUST NOT 被自动再次调用

#### Scenario: delegate 不被默认超时截断
- **WHEN** 主 Agent 调用 `delegate` 且子 Agent 的完整执行耗时超过默认工具超时
- **THEN** 该调用 MUST NOT 因默认超时被中断，子 Agent 得以正常完成

#### Scenario: LLM 侧超时不重复实现
- **WHEN** 审查本变更的实现
- **THEN** 不存在新增的 LLM 请求级超时/重试代码，LLM 侧仍走 `guarded_invoke`

### Requirement: Web 端为同步特例

现有 Web 聊天 SHALL 经由 `execute_inline` 执行；Web 端对外 API 行为 MUST 保持不变（token 序列、响应头、错误行为、断连行为均不变）。接线 SHALL 由环境变量开关控制（默认启用新路径），保留旧直调路径以便应急回退。

验证覆盖（MUST）：Web 改道的无回归证据 SHALL 来自针对 HTTP 端点的端到端回归测试，MUST NOT 以 `evals/` 门禁作为该结论的依据——`evals/agent_capture.py` 直接构造 `AgentLoop`，不经过 `api/chat_handler`、`web/routes` 与 executor，其结果对本路径的改动不敏感。

#### Scenario: Web 行为不变
- **WHEN** Web 端发起一次聊天请求
- **THEN** token 序列、`X-Session-Id` 响应头与错误行为均与改造前一致

#### Scenario: 端到端回归测试覆盖改道路径
- **WHEN** 运行测试套件
- **THEN** 存在打到 `/chat/stream` 的端到端测试（LLM 用 fake、离线确定性），覆盖 token 序列、会话标识回传、多轮上下文接续、跨会话不串号

### Requirement: 提交方身份传递

任务 SHALL 可携带提交者的用户标识（`user_id`），并透传至会话编排层用于长期偏好读取；缺省不传时 MUST 沿用既有默认用户，Web 端行为不变。

理由：群聊场景下同一话题由多人共享，会话历史按话题共享是正确的，但长期偏好按用户隔离才正确。现有编排从不传 `user_id`，全部落到 `default_user`，直接接入群聊会导致所有成员的偏好互相污染。`SessionStore.get_or_create` 已支持该参数，仅缺调用方传值。

#### Scenario: 群成员偏好隔离
- **WHEN** 同一话题内两位不同成员先后发言
- **THEN** 两人共享该话题的会话历史，但各自的长期偏好按各自 user_id 分别读取

#### Scenario: Web 端行为不变
- **WHEN** Web 端提交任务且未携带 user_id
- **THEN** 沿用既有默认用户，长期偏好读取行为与改造前一致
