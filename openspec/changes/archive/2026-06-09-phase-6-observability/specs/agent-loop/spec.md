## ADDED Requirements

### Requirement: 循环接入 Tracer 且向后兼容

`AgentLoop` SHALL 接受一个可选的 tracer 依赖（构造参数，缺省为无）。当注入 tracer 时，`AgentLoop` MUST 为整次 run 开一个 root span、为每一步开一个 child span，并在各步记录 `thought`（LLM 文本/决策）、`tool_call`（工具名+参数）、`observation`（工具结果）、该步 latency 与 token 近似。当未注入 tracer 时，`AgentLoop` 的行为 MUST 与未接入可观测性前完全一致（既有 `on_tool_call`/`on_observation` 钩子语义保留、可 no-op），不得引入任何可观测路径上的回归。

#### Scenario: 注入 tracer 时产生可回放 trace

- **WHEN** 用注入了 tracer 的 `AgentLoop` 跑一次含工具调用的请求
- **THEN** tracer 收到一个 root span 与每步的 child span，工具步的 span 记录了 tool_call、observation 与该步 latency

#### Scenario: 未注入 tracer 时行为不变

- **WHEN** 不传 tracer 构造 `AgentLoop` 并运行既有路径
- **THEN** 循环行为与接入可观测性之前一致（直接回复 / 单步 / 多步 / max_steps / 护栏兜底均不变），不抛错、不回归

#### Scenario: tracer 不影响护栏与错误隔离

- **WHEN** 注入 tracer 的同时发生工具异常或触达护栏（预算/打转/重试耗尽）
- **THEN** 既有错误回灌与 `[REPLY]` 兜底语义不变，tracer 仅记录相应 span/事件，不改变控制流
