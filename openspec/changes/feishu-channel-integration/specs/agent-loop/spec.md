# agent-loop 规格（delta）

## MODIFIED Requirements

### Requirement: 工具失败不崩循环

当某次工具分发抛出异常时，`AgentLoop` SHALL 捕获该异常、把错误信息作为该工具调用的 tool message 喂回（而非让异常冒泡终止整个请求），使模型有机会在后续步骤自愈或改用其它工具。当工具分发因权限策略被拒绝时，`AgentLoop` SHALL 同样把结构化拒绝结果作为该工具调用的 tool message 喂回，不执行该工具的副作用、也不崩溃循环。

`AgentLoop` SHALL 对每次工具分发施加超时，取值来自该工具的 `timeout` 声明（见 `tool-layer`「工具定义结构」），未声明时取可配置的全局缺省（默认 60 秒）。超时后 MUST 中断该次调用，并把「工具超时」作为该 tool_call_id 的错误结果按同一回灌路径喂回；该工具 MUST NOT 被自动重试。

「超时不重试」沿用工具分发既有的刻意不对称：工具可能有副作用（如写库下单），重试等于重复执行，故只做错误隔离。与之相对，LLM 请求的超时与重试由 `guardrails` 承担（见「LLM 调用经护栏执行」），本需求 MUST NOT 在工具层重复实现 LLM 侧的超时或重试。

#### Scenario: 工具抛异常时回灌错误

- **WHEN** 某个工具的 dispatch 抛出异常
- **THEN** `AgentLoop` 捕获异常，把错误描述作为该 tool_call_id 的 tool message 喂回，并继续下一轮，不使整个请求崩溃

#### Scenario: 工具被权限拒绝时回灌拒绝结果

- **WHEN** 某个危险工具调用被注入的权限策略拒绝
- **THEN** `AgentLoop` 把带拒绝理由的结构化结果作为该 tool_call_id 的 tool message 喂回，不执行其 handler，并继续下一轮

#### Scenario: 工具超时按错误结果回灌

- **WHEN** 某次工具分发耗时超过该工具适用的超时阈值
- **THEN** 该调用被中断，「工具超时」作为该 tool_call_id 的 tool message 喂回，循环继续而非崩溃

#### Scenario: 超时的工具不被重试

- **WHEN** 某次工具分发因超时被中断
- **THEN** `AgentLoop` MUST NOT 自动再次调用该工具

#### Scenario: 声明了超时豁免的工具不被中断

- **WHEN** 主 Agent 调用豁免了默认超时的 `delegate`，且其内部子 Agent 的完整执行超过全局缺省上限
- **THEN** 该调用 MUST NOT 因默认超时被中断，子 Agent 得以正常完成
