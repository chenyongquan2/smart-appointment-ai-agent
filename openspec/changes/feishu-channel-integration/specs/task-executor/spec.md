# task-executor 规格

## ADDED Requirements

### Requirement: 任务式接口
系统 SHALL 提供 Channel 与 Agent 之间的任务式接口：`submit(task) → task_id`，任务终态（完成/失败/超时）通过回调通知提交方。Channel MUST NOT 直接同步调用 AgentLoop。

#### Scenario: 提交与回调
- **WHEN** Channel 提交一个任务
- **THEN** 立即获得 task_id，任务终态时提交方的回调被调用且携带结果或错误

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

### Requirement: 墙钟超时兜底
每个任务 SHALL 有可配置的墙钟总超时（默认 600 秒）；超时 MUST 终止任务并以超时终态回调，MUST NOT 让任务无限期运行。

#### Scenario: 超时终止
- **WHEN** 任务执行超过墙钟上限
- **THEN** 任务被终止，提交方收到超时终态回调

### Requirement: LLM 请求级 hang 看门狗
系统 SHALL 检测单次 LLM 请求的 hang（可配置阈值，默认 60 秒无首包）；检测窗口 MUST 只覆盖"等待模型响应"阶段，工具执行耗时 MUST NOT 计入。触发后 SHALL 中断当前请求并重试（次数可配，默认 2 次），重试耗尽转任务失败终态。

#### Scenario: hang 重试
- **WHEN** 一次 LLM 请求超过阈值无响应
- **THEN** 该请求被中断并重试，任务不因单次 hang 直接失败

#### Scenario: 工具慢不误杀
- **WHEN** 某工具执行耗时超过 hang 阈值但 LLM 响应正常
- **THEN** 看门狗不触发

### Requirement: Web 端为同步特例
现有 Web 聊天 SHALL 经由同一任务接口执行（提交后原地等待结果流式返回）；Web 端对外 API 行为 MUST 保持不变。

#### Scenario: Web 行为不变
- **WHEN** Web 端发起一次聊天请求
- **THEN** 响应格式与改造前一致，现有测试与 evals 门禁全绿
