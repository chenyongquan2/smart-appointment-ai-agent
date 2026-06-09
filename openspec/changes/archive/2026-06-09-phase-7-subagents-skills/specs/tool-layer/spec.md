## ADDED Requirements

### Requirement: ToolRegistry 支持工具子集构建

`ToolRegistry` SHALL 支持按一组工具名构建一个仅含这些工具的**子集 registry**（切片），用于给子 Agent 提供其领域所需的工具子集。子集构建 MUST 复用既有工具实例（不复制、不重写业务逻辑）；请求子集时若包含未注册的工具名 MUST 报错。子集 registry 的注册/分发/导出 schema 行为与全量 registry 一致。

#### Scenario: 构建仅含指定工具的子集

- **WHEN** 从全量 registry 请求构建含 `["search_knowledge"]` 的子集
- **THEN** 返回的子集 registry 仅暴露 `search_knowledge`，其分发与 schema 导出仅覆盖该工具

#### Scenario: 子集包含未注册工具名时报错

- **WHEN** 请求构建包含某个未注册工具名的子集
- **THEN** registry 抛出明确错误，指出该工具不存在

### Requirement: delegate 编排型工具

工具层 SHALL 提供一个 `delegate` 工具，遵循既有工具四要素（`name`/`description`/Pydantic args schema/handler）并定义在独立文件中。与领域工具不同，`delegate` 是**编排型工具**：其 handler 不调用 `services/`，而是把任务转交给指定的子 Agent 执行并返回其汇总结果。`delegate` 的入参 MUST 经 Pydantic 校验，且其 `description` MUST 向模型清晰说明可派生的子 Agent 选项与各自职责。既有领域工具与默认全量 registry 的行为 MUST 不受影响。

#### Scenario: delegate 暴露工具四要素

- **WHEN** 读取 `delegate` 工具
- **THEN** 它暴露非空 `name`、说明子 Agent 选项的 `description`、一个 Pydantic args schema、以及一个可调用 handler

#### Scenario: delegate 分发到子 Agent

- **WHEN** 以合法的子 Agent 标识与任务调用 `delegate`
- **THEN** 它把任务转交对应子 Agent 执行，返回其汇总结果，不直接调用任何 `services/` 业务方法
