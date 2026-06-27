# observability Specification

## Purpose
TBD - created by archiving change phase-6-observability. Update Purpose after archive.
## Requirements
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

### Requirement: Tracer 透传进子 Agent 的内层 AgentLoop

当主 Agent 经 `delegate` 派生子 Agent 时，注入主 `AgentLoop` 的 `Tracer` SHALL 能透传进子 Agent 的内层 `AgentLoop`，使子 Agent 步内的 `tool_call` / `observation` / `latency` / `tokens` 被正常记录并经 exporter 导出。子 Agent 的工具调用 MUST NOT 因 tracer 未传递而对可观测层不可见。

子 Agent 的内层 loop MAY 各自开自己的 root span（即与主 trace 不强制同 `trace_id`、不强制嵌套为父子层级）；本要求只保证「子 Agent 工具调用可被导出」，不要求跨 loop 的父 span 嵌套传播。

未注入 tracer（缺省 `NoopTracer`）时，子 Agent 行为 MUST 与透传前完全一致（向后兼容、零副作用）。

#### Scenario: 子 Agent 工具调用可被导出

- **WHEN** 用注入了真 `Tracer` 的主 `AgentLoop` 跑一次经 `delegate` 派生子 Agent、并由子 Agent 执行领域工具的请求
- **THEN** 该次运行导出的 span 中包含子 Agent 步内的 `tool_call`（名称+参数）与 `observation`（结果）

#### Scenario: 未注入 tracer 时行为不变

- **WHEN** 主 `AgentLoop` 未注入 tracer（走缺省 `NoopTracer`）并派生子 Agent
- **THEN** 子 Agent 不产生任何 span 导出，运行行为与透传改造前完全一致

### Requirement: 持久化文件 SpanExporter

系统 SHALL 提供一个落盘型 `SpanExporter` 实现（如 `FileSpanExporter`），把每个结束的 span 经 `Span.to_dict()` 序列化为单行 JSON 追加写入磁盘文件（默认目录 `evals/traces/`）。该 exporter MUST 满足既有 `SpanExporter` 协议的「不得抛出」契约：`export(span)` 内部 MUST 捕获自身一切异常（如磁盘/IO 错误），失败时 MUST 仅记 warning 并继续，MUST NOT 把异常抛回主循环。该 exporter MUST NOT 依赖 OpenTelemetry 运行时。

#### Scenario: span 以单行 JSON 追加落盘

- **WHEN** 用接了 `FileSpanExporter` 的 tracer 跑一次请求
- **THEN** 该次运行的每个结束 span 以单行 JSON（`ensure_ascii=False`）追加写入目标文件，可逐行解析回与 `Span.to_dict()` 一致的结构

#### Scenario: 写盘失败不拖垮主流程

- **WHEN** 落盘写入因 IO 错误失败
- **THEN** `export` 不抛出异常，仅记一条 warning，主循环继续正常产出回复

### Requirement: 生产 AgentLoop 接入 trace 采样

生产请求入口（`api/chat_handler.py` 的主 `AgentLoop`）SHALL 注入一个 `Tracer` 与落盘 exporter，使真实对话产出可检索的持久化 trace；tracer MUST 同样透传进经 `delegate` 派生的子 Agent（复用既有「Tracer 透传进子 Agent」要求），以采到领域工具调用。采样口径为 **全量落盘 + 错误优先**：默认保留全部 trace；命中失控信号（循环达 `max_steps`、工具调用异常、回复带 `[ERROR]`、跑满步数的兜底回复）的 trace MUST 必留。系统 SHALL 提供一个 `sample_rate` 旋钮（默认 `1.0`），当配置为 `<1.0` 时按比例对「非错误」trace 采样，但**错误 trace 不受采样率影响、始终保留**。接入 tracer MUST NOT 改变既有流式回复语义（`[THOUGHT]`/`[REPLY]`/`[ERROR]` 前缀不变）。

#### Scenario: 真实对话留下可检索 trace

- **WHEN** 经生产入口跑完一次带 `session_id` 的对话
- **THEN** 在 trace 落盘目录产生该次运行的 span 记录，其 attributes 含 `session_id`，且回复的流式前缀语义与接入前一致

#### Scenario: 错误 trace 不受采样率丢弃

- **WHEN** `sample_rate` 配为小于 1.0，且某次运行命中失控信号（如达到 `max_steps` 或工具异常）
- **THEN** 该次 trace 仍被完整保留落盘，不因采样率被丢弃

