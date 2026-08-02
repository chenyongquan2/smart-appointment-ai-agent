# tool-layer Specification

## Purpose

定义 harness 的工具层:把既有 `services/` 能力封装为模型可调用的工具,提供统一的 `ToolRegistry` 完成注册、按名分发与参数校验,并能把工具导出为 Anthropic / OpenAI 两种 LLM tools schema。工具仅为 `services/` 的薄封装,不重写业务逻辑,保持单向依赖。

## Requirements

### Requirement: 工具定义结构

每个工具 SHALL 定义在其所属**领域包**的 `domains/<domain>/tools/` 下的独立文件中（一个概念一个文件），并声明四要素：唯一 `name`（snake_case）、面向模型的 `description`、入参 schema（Pydantic v2 模型）、以及 `handler`（可调用对象）。工具 handler MUST 仅作为 `services/` 的薄封装，不得重写业务逻辑，且 MUST NOT 反向依赖 `agents/` 或 `harness/runtime`。每个工具 SHALL 另外声明一个 `dangerous` 标记（布尔，默认 `False`）以标识其是否为有副作用的危险操作；带副作用的写操作工具（如 `create_appointment`）MUST 标记为 `dangerous=True`，只读查询工具保持默认 `False`。

每个工具 SHALL 另外支持一个可选的 `timeout` 声明（秒，默认 `None`）：`None` 表示采用全局缺省工具超时，显式数值覆盖之，显式声明为不限时则该工具不受超时约束。超时的施加与语义见 `agent-loop` 的「工具失败不崩循环」。

超时声明在工具自身而非运行时全局常量，原因是不同工具的合理耗时相差数量级：`delegate` 的 handler 内部运行的是一整个子 AgentLoop（多步 LLM 调用），与一次本地 DB 查询共用同一个上限必然误杀其一。该设计也使后续接入网络工具时，超时成为工具声明处的自然填空，无需改动运行时。

工具编写约定 SHALL 写明超时的适用边界：超时依赖 `asyncio` 的取消机制，只能中断在 await 点让出控制权的 handler；内部执行同步阻塞调用（同步 SQLite / FAISS / 子进程等）的工具即使声明了 `timeout` 也不会被真正中断，此类工具 MUST 自行将阻塞调用下沉到线程池才能获得超时保护。

#### Scenario: 工具暴露四要素

- **WHEN** 注册中心或测试读取任一已实现工具
- **THEN** 该工具暴露非空 `name`、非空 `description`、一个 Pydantic `BaseModel` 子类作为 args schema、以及一个可调用 `handler`

#### Scenario: 工具为薄封装

- **WHEN** 调用任一工具的 handler
- **THEN** 它将参数转交给对应 `services/` 方法并返回其结果，不包含独立的业务规则实现

#### Scenario: 危险工具被正确标记

- **WHEN** 读取 `create_appointment` 与只读工具（如 `search_knowledge`）的 `dangerous` 标记
- **THEN** `create_appointment` 的 `dangerous` 为 `True`，只读工具的 `dangerous` 为 `False`

#### Scenario: 工具可声明自己的超时

- **WHEN** 读取任一工具的 `timeout` 声明
- **THEN** 未显式声明的工具取值为 `None`（表示采用全局缺省），显式声明的工具取值为其自身设定

#### Scenario: delegate 豁免默认超时

- **WHEN** 读取 `delegate` 工具的 `timeout` 声明
- **THEN** 它显式豁免全局缺省工具超时，不会因默认上限而在子 Agent 正常执行期间被中断

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
