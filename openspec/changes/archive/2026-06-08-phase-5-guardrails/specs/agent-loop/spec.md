## MODIFIED Requirements

### Requirement: 步数上限防失控

`AgentLoop` SHALL 接受一个 `max_steps` 上限；当循环达到该上限仍未得到最终回复时，MUST 停止循环并返回一个安全的兜底回复，绝不无限循环。除 `max_steps` 外，`AgentLoop` SHALL 额外受 token 预算上限与打转检测两道护栏约束：当累计估算 token 超过配置上限，或连续达到配置次数的完全相同工具调用（相同名称与参数）时，MUST 同样停止循环并返回安全兜底回复。这些终止条件 MUST 复用既有 `[REPLY]` 兜底语义，不新增对外前缀。

#### Scenario: 达到 max_steps 时终止

- **WHEN** LLM 连续每一步都返回工具调用、始终不产出最终回复，直到步数达到 `max_steps`
- **THEN** `AgentLoop` 停止循环并产出兜底回复，不再发起新的 LLM 调用

#### Scenario: 超过 token 预算时终止

- **WHEN** 单次请求累计估算 token 超过配置的预算上限
- **THEN** `AgentLoop` 停止循环、不再发起新的 LLM 调用，并以 `[REPLY]` 前缀产出安全兜底回复

#### Scenario: 检测到打转时终止

- **WHEN** LLM 连续达到 `repeat_limit` 次返回名称与参数都完全相同的工具调用
- **THEN** `AgentLoop` 判定打转并停止循环，以 `[REPLY]` 前缀产出安全兜底回复

### Requirement: 工具失败不崩循环

当某次工具分发抛出异常时，`AgentLoop` SHALL 捕获该异常、把错误信息作为该工具调用的 tool message 喂回（而非让异常冒泡终止整个请求），使模型有机会在后续步骤自愈或改用其它工具。当工具分发因权限策略被拒绝时，`AgentLoop` SHALL 同样把结构化拒绝结果作为该工具调用的 tool message 喂回，不执行该工具的副作用、也不崩溃循环。

#### Scenario: 工具抛异常时回灌错误

- **WHEN** 某个工具的 dispatch 抛出异常
- **THEN** `AgentLoop` 捕获异常，把错误描述作为该 tool_call_id 的 tool message 喂回，并继续下一轮，不使整个请求崩溃

#### Scenario: 工具被权限拒绝时回灌拒绝结果

- **WHEN** 某个危险工具调用被注入的权限策略拒绝
- **THEN** `AgentLoop` 把带拒绝理由的结构化结果作为该 tool_call_id 的 tool message 喂回，不执行其 handler，并继续下一轮

## ADDED Requirements

### Requirement: LLM 调用经护栏执行

`AgentLoop` 对 LLM 的每次调用 SHALL 经超时与重试护栏执行，而非裸调用；当护栏重试耗尽抛出护栏异常时，`AgentLoop` MUST 捕获并以 `[REPLY]` 前缀产出安全兜底回复，绝不让底层 LLM 异常冒泡到 Channel 层。

#### Scenario: LLM 持续失败时优雅降级

- **WHEN** LLM 调用持续超时/失败直至护栏重试耗尽
- **THEN** `AgentLoop` 捕获护栏异常，以 `[REPLY]` 前缀产出安全兜底回复，不抛出异常、不崩溃请求
