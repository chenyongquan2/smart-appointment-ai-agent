## ADDED Requirements

### Requirement: 全链路 Trace 与 Span 模型

系统 SHALL 提供一个 `Tracer`，把一次 `AgentLoop` 请求建模为一条带唯一 `trace_id` 的 trace：整次 run 对应一个 root span，循环每一步对应一个 child span（携带 `parent_id` 指向 root 或上一步）。每个 span MUST 记录名称、开始/结束时刻与据此计算的 latency，并 MAY 携带 `attributes`（如 `session_id`、近似 token 数、工具名、参数）。同一 `trace_id` 下的所有 span MUST 可据 `trace_id` 检索并按 parent 关系重建为可回放的层级。

#### Scenario: 一次请求串成一条可回放 trace

- **WHEN** 用注入了 tracer 的 `AgentLoop` 跑完一次多步请求
- **THEN** 产生一个 root span 与若干 child span，全部带同一 `trace_id`，每个 span 含 latency，且 child span 经 `parent_id` 可重建为层级

#### Scenario: trace_id 与 session 关联但不耦合

- **WHEN** 请求带 `session_id` 运行
- **THEN** span 的 attributes 含该 `session_id` 用于检索，但 tracer 不读写会话状态、不参与会话隔离逻辑

### Requirement: 记录 thought / tool_call / observation / latency / tokens

`Tracer` SHALL 支持记录五类信息：`thought`（每步 LLM 产出的文本/决策）、`tool_call`（工具名与参数）、`observation`（工具结果）、`latency`（每步与端到端耗时）、`tokens`（复用既有 `estimate_tokens` 的近似值，并标注为近似）。这些信息 MUST 落到对应 span 的 events 或 attributes 上。

#### Scenario: 工具步记录调用与结果

- **WHEN** 某一步 LLM 返回工具调用并执行
- **THEN** 对应 span 记录 `tool_call`（名称+参数）与 `observation`（结果），并记录该步 latency

#### Scenario: token 记为近似值

- **WHEN** 记录某步或整次请求的 token
- **THEN** 该值取自 `estimate_tokens` 的字符数近似，并被标注为近似（approximate），不声称为精确计费

### Requirement: 可插 SpanExporter 抽象

`Tracer` 的输出 SHALL 经一个 `SpanExporter` 协议（`export(span)`）解耦，使输出后端可替换而不改动业务/循环代码。系统 SHALL 至少提供：一个默认的 JSON 日志 exporter（复用 `config/logging_setup.py` 的结构化日志）；一个可选的 OpenTelemetry exporter。默认路径 MUST NOT 依赖 OpenTelemetry 运行时。

#### Scenario: 默认 JSON 日志 exporter 零额外依赖

- **WHEN** 用默认 exporter 构造 tracer 并产生 span
- **THEN** span 以单行 JSON 经既有日志输出，且全程不 import OpenTelemetry

#### Scenario: 注入自定义 exporter 可断言

- **WHEN** 注入一个收集型 fake exporter 跑一次请求
- **THEN** 可从该 exporter 取得全部导出的 span 并断言其 trace_id、层级、latency 与记录的事件

### Requirement: OpenTelemetry 导出与离线可测

系统 SHALL 提供一个 OpenTelemetry exporter，把内部 span 映射为 OTel span：root/child 层级一致、`duration` 取自 latency、`attributes` 含 token 近似/工具名/参数。该 exporter MUST 可对接 OTel `InMemorySpanExporter` 在单元测试中离线断言，全程不发起网络调用。OpenTelemetry 相关 import SHALL 隔离，仅在显式启用该 exporter 时才需要其运行时；未安装/未启用时默认路径 MUST 不受影响。

#### Scenario: 用 InMemorySpanExporter 离线断言 OTel span

- **WHEN** 用接到 `InMemorySpanExporter` 的 OTel exporter 跑一次请求
- **THEN** 可从内存读取到对应的 OTel span，其层级、duration 与 attributes 与内部 span 一致，且测试不触网

#### Scenario: OTel 未启用时默认路径不受影响

- **WHEN** 使用默认 JSON 日志 exporter（不启用 OTel）
- **THEN** tracer 正常工作且不 import OpenTelemetry，不因 OTel 缺失而报错
