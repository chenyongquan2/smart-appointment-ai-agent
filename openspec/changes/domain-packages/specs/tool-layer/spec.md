## MODIFIED Requirements

### Requirement: 核心工具集

工具层的工具集 SHALL 由**当前装载的领域包**提供（见 `domain-packages` 能力），而非在 `harness/` 中写死枚举。工具的定义结构（`name` / `description` / `args_schema` / `handler` / `dangerous` / `timeout`）与「工具是 `services/` 的薄封装、MUST NOT 重写业务逻辑」的约束不变。

`appointment` 领域包 SHALL 提供以下工具，每个内部调用既有 service 或已声明的外部端口：`search_knowledge` → 知识库检索端口（`KnowledgeSearchPort`，见「知识库检索端口」需求）；`find_technician` → 技师匹配 service；`check_availability` → `AppointmentService.is_technician_available`；`create_appointment` → `AppointmentService.save_appointment`；`get_user_preferences` → `UserBehaviorService`。每个工具的入参 MUST 经 Pydantic schema 校验。

工具层 MUST NOT 横向依赖 `agents/`：工具的业务实现 SHALL 位于 `services/`。

#### Scenario: 工具集来自装载的领域包

- **WHEN** 装载某个领域包并构建 registry
- **THEN** registry 中的工具恰为该领域包声明的工具集，`harness/` 中不存在写死的工具枚举

#### Scenario: search_knowledge 经端口检索知识库

- **WHEN** 以合法 `query` 和 `top_k` 调用 `search_knowledge`，且已配置可用的知识库检索端口
- **THEN** 工具把已校验的参数转交该端口，并返回端口给出的结构化检索结果列表，工具层自身 MUST NOT 实现检索逻辑

#### Scenario: check_availability 返回可用性

- **WHEN** 以合法 `technician_id`、`start_time`、`end_time` 调用 `check_availability`
- **THEN** 工具调用 `AppointmentService.is_technician_available` 并返回布尔可用性结果

#### Scenario: 非法入参被拒绝

- **WHEN** 以缺失必填字段或类型错误的参数调用任一工具
- **THEN** Pydantic 校验在进入 service 之前抛出验证错误，service 不被调用

#### Scenario: 工具层不依赖 agents

- **WHEN** 检索工具层的 import
- **THEN** 不存在对 `agents/` 的依赖；技师匹配等业务实现位于 `services/`
