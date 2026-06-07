## ADDED Requirements

### Requirement: 工具定义结构

每个工具 SHALL 定义在 `harness/tools/` 下的独立文件中（一个概念一个文件），并声明四要素：唯一 `name`（snake_case）、面向模型的 `description`、入参 schema（Pydantic v2 模型）、以及 `handler`（可调用对象）。工具 handler MUST 仅作为 `services/` 的薄封装，不得重写业务逻辑，且 MUST NOT 反向依赖 `agents/` 或 `harness/runtime`。

#### Scenario: 工具暴露四要素

- **WHEN** 注册中心或测试读取任一已实现工具
- **THEN** 该工具暴露非空 `name`、非空 `description`、一个 Pydantic `BaseModel` 子类作为 args schema、以及一个可调用 `handler`

#### Scenario: 工具为薄封装

- **WHEN** 调用任一工具的 handler
- **THEN** 它将参数转交给对应 `services/` 方法并返回其结果，不包含独立的业务规则实现

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

系统 SHALL 提供 `ToolRegistry`，支持注册工具、按 `name` 查找、按 `name` 分发（dispatch）调用。分发 MUST 用工具的 args schema 校验传入参数后再执行 handler。注册重名工具 MUST 报错；分发未注册的工具名 MUST 报错。

#### Scenario: 按名分发到 handler

- **WHEN** 调用 `registry.dispatch("search_knowledge", {"query": "...", "top_k": 3})`
- **THEN** registry 用该工具的 args schema 校验参数，调用其 handler，并返回 handler 结果

#### Scenario: 未知工具名报错

- **WHEN** 调用 `registry.dispatch` 传入未注册的工具名
- **THEN** registry 抛出明确错误，指出该工具不存在

#### Scenario: 重名注册报错

- **WHEN** 向 registry 注册一个 `name` 已存在的工具
- **THEN** registry 抛出明确错误，拒绝覆盖

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
