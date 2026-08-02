## MODIFIED Requirements

### Requirement: 核心工具集

工具层 SHALL 提供以下工具，每个内部调用既有 service 或已声明的外部端口：`search_knowledge` → 知识库检索端口（`KnowledgeSearchPort`，见「知识库检索端口」需求）；`find_technician` → `TechnicianService`/`AppointmentService`；`check_availability` → `AppointmentService.is_technician_available`；`create_appointment` → `AppointmentService.save_appointment`；`get_user_preferences` → `UserBehaviorService`。每个工具的入参 MUST 经 Pydantic schema 校验。

#### Scenario: search_knowledge 经端口检索知识库

- **WHEN** 以合法 `query` 和 `top_k` 调用 `search_knowledge`，且已配置可用的知识库检索端口
- **THEN** 工具把已校验的参数转交该端口，并返回端口给出的结构化检索结果列表，工具层自身 MUST NOT 实现检索逻辑

#### Scenario: check_availability 返回可用性

- **WHEN** 以合法 `technician_id`、`start_time`、`end_time` 调用 `check_availability`
- **THEN** 工具调用 `AppointmentService.is_technician_available` 并返回布尔可用性结果

#### Scenario: 非法入参被拒绝

- **WHEN** 以缺失必填字段或类型错误的参数调用任一工具
- **THEN** Pydantic 校验在进入 service 之前抛出验证错误，service 不被调用

## ADDED Requirements

### Requirement: 知识库检索端口

系统 SHALL 把知识库检索定义为一个**可替换的端口**（`KnowledgeSearchPort`），由 `search_knowledge` 工具依赖该端口而非任何具体检索实现。端口的入参口径 SHALL 与 `SearchKnowledgeArgs` 一致（`query` / `top_k` / 可选 `category`），返回值 SHALL 为结构化文档列表。

未配置任何实现时，缺省实现 SHALL 使该次调用以**明确标示"知识库未接入"的失败**收场，并 SHALL 走既有的单工具失败回灌路径（结果以 `TOOL_FAILURE_PREFIX` 开头、作为 observation 回灌模型、agent loop 继续执行）。

- MUST NOT 静默返回空列表——会被模型误读为"查过了、库里没有这条信息"，进而凭训练知识编造价格与政策。
- MUST NOT 返回可被判定为"执行成功"的结果——否则 `任务成功率` 会把"根本没检索到"记成达成业务终态，指标失真比指标下探更有害。
- MUST NOT 让异常冒出 agent loop 之外而中断循环。

`search_knowledge` 的 `name`、`description`、`args_schema`、`dangerous`（只读，`False`）SHALL 保持不变，使既有 registry 注册、子 Agent 工具切片与评估用例标注均不受实现替换影响。

#### Scenario: 未接入远程 RAG 时以明确的失败收场

- **WHEN** 未配置任何知识库检索实现，模型调用 `search_knowledge`
- **THEN** 回灌给模型的 observation 明确标示"知识库尚未接入"、且以 `TOOL_FAILURE_PREFIX` 开头（因此 `任务成功率` 判定为未达成、坏信号可被 triage 甄别），agent loop MUST 继续执行，模型据此如实告知用户而非编造答案

#### Scenario: 注入实现后工具行为不变

- **WHEN** 注入一个返回固定文档的端口实现（如测试/评估用 fake），再调用 `search_knowledge`
- **THEN** 工具返回该实现给出的文档列表，且工具的 `name` / `description` / `args_schema` / `dangerous` 与替换前完全一致

#### Scenario: 端口可替换保证评估的离线确定性

- **WHEN** 评估或测试注入固定返回的端口实现
- **THEN** `search_knowledge` 的返回不依赖任何外部网络服务，同一输入 MUST 得到同一结果

#### Scenario: 端口实现替换不触及上层

- **WHEN** 把端口实现从"未接入"换成任意具体实现（如接入独立 RAG 项目的远程 client）
- **THEN** `harness/tools/registry.py` 的注册、子 Agent 的工具切片、评估用例中对 `search_knowledge` 的标注 MUST 均无需改动
