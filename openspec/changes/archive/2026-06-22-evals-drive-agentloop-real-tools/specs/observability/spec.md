## ADDED Requirements

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
