# tool-layer Specification

## Purpose

定义 harness 的工具层:把既有 `services/` 能力封装为模型可调用的工具,提供统一的 `ToolRegistry` 完成注册、按名分发与参数校验,并能把工具导出为 Anthropic / OpenAI 两种 LLM tools schema。工具仅为 `services/` 的薄封装,不重写业务逻辑,保持单向依赖。

## Requirements

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

### Requirement: 核心工具集

工具层 SHALL 提供以下工具，每个内部调用既有 service：`search_knowledge` → `KnowledgeService.search`；`find_technician` → `TechnicianService`/`AppointmentService`；`check_availability` → `AppointmentService.is_technician_available`；`create_appointment` → `AppointmentService.save_appointment`；`get_user_preferences` → `UserBehaviorService`。每个工具的入参 MUST 经 Pydantic schema 校验。

#### Scenario: search_knowledge 调用知识库

- **WHEN** 以合法 `query` 和 `top_k` 调用 `search_knowledge`
- **THEN** 工具调用 `KnowledgeService.search` 并返回结构化检索结果列表

#### Scenario: check_availability 返回可用性

- **WHEN** 以合法 `technician_id`、`start_time`、`end_time` 调用 `check_availability`
- **THEN** 工具调用 `AppointmentService.is_technician_available` 并返回布尔可用性结果

#### Scenario: 非法入参被拒绝

- **WHEN** 以缺失必填字段或类型错误的参数调用任一工具
- **THEN** Pydantic 校验在进入 service 之前抛出验证错误，service 不被调用

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

### Requirement: 导出 LLM tools schema

`ToolRegistry` SHALL 能把已注册工具导出为 LLM 可用的 tools schema，且 MUST 同时支持 **Anthropic** 与 **OpenAI** 两种格式。导出的 schema MUST 由各工具的 Pydantic args schema 生成，包含工具的 `name`、`description` 与 JSON Schema 参数。

#### Scenario: 导出 OpenAI 格式

- **WHEN** 调用 registry 的 OpenAI schema 导出方法
- **THEN** 返回一个工具列表，每项含 `type: "function"` 与 `function.name`/`function.description`/`function.parameters`（JSON Schema）

#### Scenario: 导出 Anthropic 格式

- **WHEN** 调用 registry 的 Anthropic schema 导出方法
- **THEN** 返回一个工具列表，每项含 `name`/`description`/`input_schema`（JSON Schema）

#### Scenario: schema 源于 Pydantic 模型

- **WHEN** 某工具的 args schema 新增或修改一个字段
- **THEN** 两种格式导出的参数 JSON Schema 都相应反映该字段，无需手写 schema

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
