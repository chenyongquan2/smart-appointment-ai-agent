## ADDED Requirements

### Requirement: AgentLoop 作为子 Agent 复用执行体

`AgentLoop` SHALL 可被复用为子 Agent 的执行体：以一个仅含该子 Agent 工具子集的 `ToolRegistry` 与该子 Agent 专用 system prompt 构造一个 `AgentLoop` 实例，在独立上下文里跑一次 mini TAO 循环。子 Agent 复用 `AgentLoop` 时，其既有语义（无工具调用即结束、工具结果按协议喂回、`max_steps`/预算/打转护栏、工具失败回灌、LLM 调用经护栏）MUST 保持不变。`AgentLoop` 本身 MUST 保持无状态，不感知"自己是主 Agent 还是子 Agent"。

#### Scenario: 子 Agent 复用 AgentLoop 跑独立循环

- **WHEN** 用某子 Agent 的工具子集与专用 system prompt 构造一个 `AgentLoop` 并运行一个任务
- **THEN** 该循环按既有 TAO 语义在独立上下文里执行，仅能调用该子集内的工具，并产出最终回复

#### Scenario: 复用不改变循环语义

- **WHEN** 子 Agent 的循环中发生工具异常或触达 `max_steps`/预算/打转护栏
- **THEN** 既有错误回灌与 `[REPLY]` 兜底语义不变，与顶层 `AgentLoop` 完全一致

### Requirement: 主 Agent 经 delegate 驱动派生且向后兼容

当主 Agent 的 `ToolRegistry` 注册了 `delegate` 工具时，主 `AgentLoop` SHALL 通过正常的工具调用路径分发 `delegate`、把子 Agent 的汇总结果作为 tool message 回灌，从而由模型自主决定派生哪个子 Agent——无需任何针对意图的硬编码分支。当未注册 `delegate`（即全量扁平工具集）时，`AgentLoop` 的行为 MUST 与 Phase 6 完全一致，不引入回归。

#### Scenario: 注册 delegate 时主 Agent 自主派生

- **WHEN** 主 `AgentLoop` 的 registry 含 `delegate`，模型对一个预约请求返回指向 `appointment` 子 Agent 的 `delegate` 调用
- **THEN** 主循环经既有 dispatch 路径执行 `delegate`，把子 Agent 结果作为 tool message 回灌，并据此产出最终回复

#### Scenario: 未注册 delegate 时行为不变

- **WHEN** 用不含 `delegate` 的全量工具 registry 构造 `AgentLoop` 并运行既有路径
- **THEN** 循环行为与 Phase 6 一致（直接回复 / 单步 / 多步 / max_steps / 护栏兜底均不变），不回归
