# guardrails Specification

## Purpose

定义 harness 运行时的护栏（guardrails）能力：在 agent 循环与工具分发周围施加防失控与安全约束——LLM 调用的超时与有限次退避重试、副作用工具不被重试、单次请求的 token 预算上限、原地打转检测、以及危险操作的权限闸门。全部护栏可在不依赖真实 API key、不触网的前提下做确定性单元测试，覆盖成功、失败、降级与拒绝路径。

## Requirements

### Requirement: LLM 调用超时与重试

harness SHALL 提供一个护栏 helper，对 LLM 的异步调用施加超时与有限次指数退避重试：单次调用超过配置的超时即视为失败；对超时与瞬时连接类异常 MUST 重试，重试间隔按指数退避（base × 2^n）增长，最多 `max_attempts` 次。退避等待 MUST 可注入（测试可用 no-op），不得在单元测试中产生真实等待。重试耗尽后 MUST 抛出一个明确的护栏异常（而非原始底层异常冒泡），由调用方转为优雅降级。

#### Scenario: 首次成功不重试
- **WHEN** 被包裹的 LLM 调用在超时内成功返回
- **THEN** helper 返回其结果，且未发生任何重试或退避等待

#### Scenario: 瞬时失败后重试成功
- **WHEN** 被包裹的 LLM 调用前若干次抛出可重试异常、随后成功
- **THEN** helper 按指数退避重试并最终返回成功结果，重试次数不超过 `max_attempts`

#### Scenario: 超时触发重试
- **WHEN** 被包裹的 LLM 调用耗时超过配置超时
- **THEN** helper 判定该次失败并按策略重试

#### Scenario: 重试耗尽抛护栏异常
- **WHEN** 被包裹的 LLM 调用持续失败直到用尽 `max_attempts`
- **THEN** helper 抛出明确的护栏异常，不让原始底层异常直接冒泡

### Requirement: 副作用工具不被重试

LLM 调用重试护栏 SHALL 只施加于（只读、幂等的）LLM 推理调用。带副作用的工具调用——尤其 `create_appointment`——MUST NOT 被该重试逻辑包裹，以避免因重试而重复执行写操作（如重复下单）。

#### Scenario: 工具调用不经 LLM 重试护栏
- **WHEN** 一次工具分发（如 `create_appointment`）失败
- **THEN** 系统不对该工具调用自动重试，失败按既有错误回灌路径处理，绝不重复执行其副作用

### Requirement: 循环 token 预算上限

harness SHALL 为单次请求的 agent 循环维护一个累计 token 预算（基于消息体量的近似估算即可），并接受一个 `max_tokens` 上限。当累计估算超过上限时，循环 MUST 停止并返回安全兜底回复，而非继续发起 LLM 调用。预算为防失控上限，不要求精确计费。

#### Scenario: 预算耗尽时终止
- **WHEN** 循环累计估算 token 超过配置的 `max_tokens` 上限
- **THEN** 循环停止、不再发起新的 LLM 调用，并产出安全兜底回复

#### Scenario: 预算充足时不干预
- **WHEN** 单次请求在预算内完成
- **THEN** 预算护栏不改变循环的正常行为

### Requirement: 打转检测

harness SHALL 检测循环"原地打转"：当连续若干次（达到配置的 `repeat_limit`）出现完全相同的工具调用（相同工具名与相同参数）时，MUST 判定为打转并停止循环、返回安全兜底回复，作为早于 `max_steps` 的逃生出口。

#### Scenario: 连续相同工具调用触发终止
- **WHEN** LLM 连续 `repeat_limit` 次返回名称与参数都完全相同的工具调用
- **THEN** 循环判定打转并停止，产出安全兜底回复

#### Scenario: 参数不同不算打转
- **WHEN** 相邻步骤调用同一工具但参数不同
- **THEN** 不触发打转检测，循环正常继续

### Requirement: 危险操作权限闸门

harness SHALL 提供一个可注入的权限策略机制：策略接收（工具、入参）并返回放行或拒绝（含理由）的结构化决定。被标记为危险（dangerous）的工具在分发前 MUST 先经策略判定；被拒绝时 MUST NOT 执行其 handler，而是把结构化拒绝结果交回调用方（经错误回灌路径喂给模型）。未配置策略时，默认放行，保持既有行为。

#### Scenario: 危险工具被策略拒绝
- **WHEN** 配置了一个拒绝 `create_appointment` 的权限策略，且模型请求调用它
- **THEN** 系统不执行该工具的 handler，返回带拒绝理由的结构化结果，不产生任何副作用

#### Scenario: 危险工具被策略放行
- **WHEN** 权限策略对某次危险工具调用返回放行
- **THEN** 系统正常执行其 handler 并返回结果

#### Scenario: 默认无策略时放行
- **WHEN** 未注入任何权限策略
- **THEN** 危险工具按既有行为正常执行，不被拦截

### Requirement: 护栏离线确定性可测

全部护栏（超时/重试、预算、打转、权限）SHALL 可在不依赖真实 API key、不触网的前提下做确定性单元测试：通过注入 fake LLM、可控异常、no-op 退避等待与显式策略对象覆盖成功、失败、降级与拒绝路径。

#### Scenario: 注入异常驱动降级路径
- **WHEN** 用注入受控超时/异常的 fake 依赖运行护栏
- **THEN** 测试确定性地观察到重试、终止或拒绝行为，全程不发起真实网络调用
