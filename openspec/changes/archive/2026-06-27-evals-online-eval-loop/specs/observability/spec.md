## ADDED Requirements

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
