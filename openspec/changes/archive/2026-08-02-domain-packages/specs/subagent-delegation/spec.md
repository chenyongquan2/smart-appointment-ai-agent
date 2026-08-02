## MODIFIED Requirements

### Requirement: 三个专用子 Agent

子 Agent 的定义 SHALL 由**当前装载的领域包**提供（见 `domain-packages` 能力），而非在 `harness/` 中写死枚举。`SubAgent` 的结构、`SubAgentRegistry` 的注册与查找、以及「工具子集 MUST 从既有工具中切片得到，不新建重复工具、不重写其业务逻辑」的约束均不变。

`appointment` 领域包 SHALL 提供三个专用子 Agent，各持有其领域工具子集：`appointment` 子 Agent 持有 `find_technician` / `check_availability` / `create_appointment` / `get_user_preferences`；`consultant` 子 Agent 持有 `search_knowledge`；`user_behavior` 子 Agent 持有 `get_user_preferences`。

#### Scenario: 子 Agent 集来自装载的领域包

- **WHEN** 装载某个领域包并构建 `SubAgentRegistry`
- **THEN** registry 中的子 Agent 恰为该领域包声明的子 Agent 集，`harness/` 中不存在写死的子 Agent 枚举

#### Scenario: 预约子 Agent 完成多步预约

- **WHEN** 把"帮我约一个明天下午有空的技师"任务派给 `appointment` 子 Agent
- **THEN** 它仅用自身工具子集（find_technician / check_availability / create_appointment 等）在独立循环里完成多步决策并返回结果

#### Scenario: 咨询子 Agent 只持有知识检索工具

- **WHEN** 检查 `consultant` 子 Agent 的工具子集
- **THEN** 它包含 `search_knowledge` 且不包含写库的 `create_appointment`
