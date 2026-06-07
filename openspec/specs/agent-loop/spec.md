# agent-loop Specification

## Purpose

定义 harness 运行时的 TAO（Thought→Action→Observation）循环：用 native tool calling 驱动 LLM 自主选择并调用工具，把工具结果喂回上下文并迭代，直至模型产出最终回复或触达步数上限。它取代「LLM 分类一次 + if/else 硬路由」成为请求编排核心，使系统能处理未预设的多步工具组合，并保持单向依赖（runtime → tools → services）。

## Requirements

### Requirement: TAO 循环编排

系统 SHALL 提供一个 `AgentLoop`，在每一步用绑定了工具 schema 的 LLM 推理：若 LLM 返回工具调用（tool calls），则按名分发到 `ToolRegistry` 执行、并把每个工具结果作为 tool message 追加回消息上下文，然后进入下一步；若 LLM 不返回工具调用（产出最终文本回复），则结束循环。循环 MUST NOT 使用 `if category == ...` 这类对意图的硬编码路由分支来决定调用哪个能力。

#### Scenario: 无工具调用时直接产出最终回复

- **WHEN** LLM 对用户输入直接返回不含 tool calls 的文本回复
- **THEN** `AgentLoop` 产出该回复并结束循环，不再调用任何工具

#### Scenario: 单步工具调用后喂回结果继续

- **WHEN** LLM 返回一个工具调用（如 `find_technician`）
- **THEN** `AgentLoop` 经 `ToolRegistry` 分发执行该工具，把结果作为对应 tool_call_id 的 tool message 追加回消息上下文，并发起下一步 LLM 推理

#### Scenario: 多步组合自主决策

- **WHEN** 一次请求需要先 `find_technician` 失败再改查替代技师再 `create_appointment`
- **THEN** `AgentLoop` 在连续多步里按 LLM 的决定依次调用相应工具，无需开发者预先写死该分支顺序

### Requirement: 工具结果按协议喂回

`AgentLoop` SHALL 把每个工具的执行结果按 LLM 协议要求构造为 tool 角色消息（携带对应的 tool_call_id），追加回消息列表后再发起下一轮 LLM 调用。同一轮若 LLM 返回多个工具调用，MUST 全部执行并各自喂回，再进入下一步。

#### Scenario: 多个并行工具调用全部喂回

- **WHEN** LLM 在同一步返回两个工具调用
- **THEN** `AgentLoop` 执行两者，分别以各自 tool_call_id 追加 tool message，下一轮 LLM 同时看到两条结果

### Requirement: 步数上限防失控

`AgentLoop` SHALL 接受一个 `max_steps` 上限；当循环达到该上限仍未得到最终回复时，MUST 停止循环并返回一个安全的兜底回复，绝不无限循环。

#### Scenario: 达到 max_steps 时终止

- **WHEN** LLM 连续每一步都返回工具调用、始终不产出最终回复，直到步数达到 `max_steps`
- **THEN** `AgentLoop` 停止循环并产出兜底回复，不再发起新的 LLM 调用

### Requirement: 离线确定性可测

`AgentLoop` SHALL 依赖注入 LLM（LangChain `BaseChatModel` 接口）与 `ToolRegistry`，使其可在不依赖真实 API key 的情况下用 fake / mock 的 LLM 做确定性单元测试，覆盖「直接回复」「单步工具」「多步组合」「达到 max_steps」四类路径。

#### Scenario: 用 fake LLM 驱动循环

- **WHEN** 用一个返回预设工具调用序列的 fake `BaseChatModel` 构造 `AgentLoop` 并运行
- **THEN** 循环按预设序列分发工具并最终产出回复，全程不发起真实网络调用

### Requirement: 保留流式编排接口与会话参数

替换硬路由后，请求编排入口 `ProcessUserInput_stream` SHALL 仍以异步流式 `yield` 输出供既有 Channel 层消费，并保留既有的 `[THOUGHT]` / `[REPLY]` / `[ERROR]` 前缀语义，调用方无需改动。`AgentLoop` 的运行接口 MUST 为 `session_id` 预留参数（本变更不实现会话隔离，留待后续）。

#### Scenario: 流式接口向后兼容

- **WHEN** 既有 Channel 层调用 `ProcessUserInput_stream(user_input)`
- **THEN** 它仍异步逐段 `yield` 文本，且 `AgentLoop` 由其内部驱动，无需调用方改动签名

### Requirement: 工具失败不崩循环

当某次工具分发抛出异常时，`AgentLoop` SHALL 捕获该异常、把错误信息作为该工具调用的 tool message 喂回（而非让异常冒泡终止整个请求），使模型有机会在后续步骤自愈或改用其它工具。

#### Scenario: 工具抛异常时回灌错误

- **WHEN** 某个工具的 dispatch 抛出异常
- **THEN** `AgentLoop` 捕获异常，把错误描述作为该 tool_call_id 的 tool message 喂回，并继续下一轮，不使整个请求崩溃
