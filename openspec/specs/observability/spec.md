# observability Specification

## Purpose
TBD - created by archiving change phase-6-observability. Update Purpose after archive.
## Requirements
### Requirement: 全链路 Trace 与 Span 模型

系统 SHALL 提供一个 `Tracer`，把一次 `AgentLoop` 请求建模为一条带唯一 `trace_id` 的 trace：整次 run 对应一个 root span，循环每一步对应一个 child span（携带 `parent_id` 指向 root 或上一步）。每个 span MUST 记录名称、开始/结束时刻与据此计算的 latency，MUST 记录一个可序列化的**墙钟**起始时刻（与单调 clock 并存、语义不混），并 MAY 携带 `attributes`（如 `session_id`、`user_id`、近似 token 数、工具名、参数）。同一 `trace_id` 下的所有 span MUST 可据 `trace_id` 检索并按 parent 关系重建为可回放的层级。

#### Scenario: 一次请求串成一条可回放 trace

- **WHEN** 用注入了 tracer 的 `AgentLoop` 跑完一次多步请求
- **THEN** 产生一个 root span 与若干 child span，全部带同一 `trace_id`，每个 span 含 latency 与墙钟起始时刻，且 child span 经 `parent_id` 可重建为层级

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

生产请求入口（`api/chat_handler.py` 的主 `AgentLoop`）SHALL 注入一个 `Tracer` 与落盘 exporter，使真实对话产出可检索的持久化 trace；tracer MUST 同样透传进经 `delegate` 派生的子 Agent（复用既有「Tracer 透传进子 Agent」要求），以采到领域工具调用。采样口径为 **全量落盘 + 错误优先**：默认保留全部 trace；命中失控信号的 trace MUST 必留。失控信号集 MUST 为：护栏耗尽、打转、工具调用异常、**工具超时（loop 级与 service 级结构化两条路径）**、跑满 `max_steps` 而未产出终态回复。系统 SHALL 提供一个 `sample_rate` 旋钮（默认 `1.0`），当配置为 `<1.0` 时按比例对「非错误」trace 采样，但**错误 trace 不受采样率影响、始终保留**。接入 tracer MUST NOT 改变既有流式回复语义（`[THOUGHT]`/`[REPLY]`/`[ERROR]` 前缀不变）。

> 口径修正（change `fix-trace-triage-blindspots`）：原信号集列有「回复带 `[ERROR]`」。该前缀是**遗留 `agents/` 路径**的产物，当前生产走的 harness `AgentLoop` 只产 `[THOUGHT]`/`[REPLY]`（含兜底回复），故该信号在现实中永不命中——原文属**规格要求了一个实现刻意不做的信号**。此处按真实落点重述，不臆造信号。

#### Scenario: 真实对话留下可检索 trace

- **WHEN** 经生产入口跑完一次带 `session_id` 的对话
- **THEN** 在 trace 落盘目录产生该次运行的 span 记录，其 attributes 含 `session_id`，且回复的流式前缀语义与接入前一致

#### Scenario: 错误 trace 不受采样率丢弃

- **WHEN** `sample_rate` 配为小于 1.0，且某次运行命中失控信号（如达到 `max_steps`、工具异常或工具超时）
- **THEN** 该次 trace 仍被完整保留落盘，不因采样率被丢弃

### Requirement: 工具超时纳入失控信号

失控信号判定 SHALL 覆盖**工具超时**这一独立故障类别，并 MUST 与「工具调用异常」分开标注（两者的补救动作不同：超时应收窄查询，异常通常是参数错或下游报错；合并会使候选失去可操作性）。判定 MUST 覆盖两条**互不重叠**的真实落点：

1. **loop 级工具超时**：`AgentLoop` 的工具派发因 `asyncio.wait_for` 掐断而回灌的超时说明文本。该文本 MUST 由**单一真相源**导出为常量并被派发处引用——同一句文案 MUST NOT 在判定模块与运行时模块各存一份字面量副本（本要求的由来即为此类复制导致的静默漂移）。
2. **service 级结构化超时**：工具**正常返回**但结果对象携带表示超时的错误分类字段（如 `error_kind == "timeout"`）。此路径 MUST 依据**结构化字段**判定，MUST NOT 依赖对 `str(结果对象)` 做子串匹配——`str(dict)` 的排版不是契约，且违反「结构化输出 > 字符串解析」准则。为此 `Tracer` 记录工具结果时 SHALL 在字符串化之前把该错误分类字段提取进 observation 事件的 payload。

判定 MUST NOT 泛化为「任何错误类字段皆为失败」：`services/repo.py` 以 `status` 表达结果，其中 `need_clone` / `branch_not_found` / `bad_env` / `need_git_url` 被显式定义为**正常引导状态**（`GUIDE_STATUS`），把它们当失败会制造误报候选。

超时信号 MUST 参与既有「错误优先留存」判定（`is_bad_trace`），使超时类 trace 在采样率 `<1.0` 时同样必留。

#### Scenario: loop 级工具超时被判为失控

- **WHEN** 某次运行中工具因超过其 `timeout` 被中断，超时说明作为 observation 回灌
- **THEN** 该 trace 的信号清单包含独立的「工具超时」标签，且不与「工具调用异常」标签混同

#### Scenario: service 级结构化超时被判为失控

- **WHEN** 工具正常返回但结果携带 `error_kind == "timeout"`
- **THEN** 该 trace 的信号清单包含「工具超时」标签（尽管 loop 层面未发生任何异常）

#### Scenario: 真实群聊的三连超时不再静默

- **WHEN** 对「同一工具连续三次超时、最终仍产出终态回复」这一真实形状的 span 序列跑判定
- **THEN** 信号清单非空（回归本要求引入前该形状返回空清单的缺陷）

#### Scenario: 超时文案改动不会静默断开信号

- **WHEN** 超时说明文案被修改
- **THEN** 因判定与派发共用同一常量，信号判定随之一致，MUST NOT 出现「文案改了、信号悄悄失效」

#### Scenario: 正常引导状态不产生信号

- **WHEN** 工具返回 `status` 属 `GUIDE_STATUS` 的正常引导结果（如 `need_clone`）
- **THEN** 该 trace 不产生任何失控信号

#### Scenario: 超时 trace 在低采样率下仍必留

- **WHEN** `sample_rate` 配为小于 1.0，且某次运行仅命中超时信号（无其它失控信号）
- **THEN** 该次 trace 仍被完整保留落盘

### Requirement: Span 墙钟时间戳与单调 clock 并存

`Span` SHALL 携带一个**墙钟**起始时刻（UTC、可序列化的绝对时间），并 MUST 进入 `Span.to_dict()` 的输出。既有 `start`/`end` 字段 MUST 保持单调 clock 语义不变（仅用于计算 latency，不受系统时间回拨影响），两套时间 MUST NOT 混用或互相替代。墙钟来源 MUST 与既有 `clock` / `id_factory` 一样**可注入**，使确定性离线单测不受真实时间影响。

#### Scenario: 落盘 span 带绝对时间

- **WHEN** 用接了落盘 exporter 的 tracer 跑一次请求
- **THEN** 每条 span 记录含墙钟起始时刻，可据此按日期/时间窗筛选，且 latency 仍由单调 clock 计算

#### Scenario: 墙钟可注入以保证确定性测试

- **WHEN** 单测注入一个固定墙钟
- **THEN** 落盘 span 的墙钟字段为该固定值，断言确定可复现

### Requirement: span 携带 user_id 及其隐私边界

root span 的 attributes SHALL 可携带 `user_id`，使多人共享同一会话（群聊）的 trace 可按人区分。`AgentLoop.run()` SHALL 以**每次调用的参数**接受 `user_id`（取缺省值时行为与接入前完全一致），MUST NOT 作为构造参数持有——`AgentLoop` 是跨请求共享的单例，构造期持有会在并发会话间串号。

隐私边界 MUST 满足：trace 落盘目录 MUST 保持在版本控制忽略范围内；从 trace 派生的评估用例 MUST NOT 携带 `user_id`（评估集进版本库）。

#### Scenario: 群聊 trace 可按人区分

- **WHEN** 同一会话内由不同提交者各跑一次请求
- **THEN** 两次的 root span attributes 各自携带对应的 `user_id`

#### Scenario: 不传 user_id 时行为不变

- **WHEN** 调用方不传 `user_id`
- **THEN** 运行行为与接入前完全一致，span 不含该属性

