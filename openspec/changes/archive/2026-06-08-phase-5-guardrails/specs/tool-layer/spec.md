## MODIFIED Requirements

### Requirement: 工具定义结构

每个工具 SHALL 定义在 `harness/tools/` 下的独立文件中（一个概念一个文件），并声明四要素：唯一 `name`（snake_case）、面向模型的 `description`、入参 schema（Pydantic v2 模型）、以及 `handler`（可调用对象）。工具 handler MUST 仅作为 `services/` 的薄封装，不得重写业务逻辑，且 MUST NOT 反向依赖 `agents/` 或 `harness/runtime`。每个工具 SHALL 另外声明一个 `dangerous` 标记（布尔，默认 `False`）以标识其是否为有副作用的危险操作；带副作用的写操作工具（如 `create_appointment`）MUST 标记为 `dangerous=True`，只读查询工具保持默认 `False`。

#### Scenario: 工具暴露四要素

- **WHEN** 注册中心或测试读取任一已实现工具
- **THEN** 该工具暴露非空 `name`、非空 `description`、一个 Pydantic `BaseModel` 子类作为 args schema、以及一个可调用 `handler`

#### Scenario: 工具为薄封装

- **WHEN** 调用任一工具的 handler
- **THEN** 它将参数转交给对应 `services/` 方法并返回其结果，不包含独立的业务规则实现

#### Scenario: 危险工具被正确标记

- **WHEN** 读取 `create_appointment` 与只读工具（如 `search_knowledge`）的 `dangerous` 标记
- **THEN** `create_appointment` 的 `dangerous` 为 `True`，只读工具的 `dangerous` 为 `False`

### Requirement: ToolRegistry 注册与分发

系统 SHALL 提供 `ToolRegistry`，支持注册工具、按 `name` 查找、按 `name` 分发（dispatch）调用。分发 MUST 用工具的 args schema 校验传入参数后再执行 handler。注册重名工具 MUST 报错；分发未注册的工具名 MUST 报错。`ToolRegistry` SHALL 支持注入一个可选的权限策略；对标记为 `dangerous` 的工具，dispatch 在执行 handler 之前 MUST 先经该策略判定，策略返回拒绝时 MUST NOT 执行 handler，而是返回带理由的结构化拒绝结果。未注入策略时，默认放行，保持既有分发行为。

#### Scenario: 按名分发到 handler

- **WHEN** 调用 `registry.dispatch("search_knowledge", {"query": "...", "top_k": 3})`
- **THEN** registry 用该工具的 args schema 校验参数，调用其 handler，并返回 handler 结果

#### Scenario: 未知工具名报错

- **WHEN** 调用 `registry.dispatch` 传入未注册的工具名
- **THEN** registry 抛出明确错误，指出该工具不存在

#### Scenario: 重名注册报错

- **WHEN** 向 registry 注册一个 `name` 已存在的工具
- **THEN** registry 抛出明确错误，拒绝覆盖

#### Scenario: 危险工具被策略拒绝时不执行

- **WHEN** registry 注入了拒绝 `create_appointment` 的权限策略，且 dispatch 该工具
- **THEN** registry 不执行其 handler，返回带拒绝理由的结构化结果，service 不被调用

#### Scenario: 无策略时危险工具正常分发

- **WHEN** registry 未注入权限策略，dispatch 一个危险工具
- **THEN** registry 按既有行为校验参数并执行 handler，返回其结果
