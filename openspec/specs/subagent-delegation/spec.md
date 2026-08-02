# subagent-delegation Specification

## Purpose

定义 harness 的子 Agent 派生机制：把不同领域的能力封装为各持工具子集与专用 system prompt 的子 Agent，复用既有 `AgentLoop` 在独立上下文里跑 mini TAO 循环，并通过 `delegate` 编排型工具由主 Agent 自主决定派生哪个子 Agent，取代按意图分类的 `if/else` 硬路由。

## Requirements

### Requirement: 子 Agent 抽象

系统 SHALL 提供一个 `SubAgent` 抽象，定义在 `harness/subagents/` 下（一个子 Agent 一个文件），声明四要素：唯一 `name`、面向主 Agent 的 `description`（说明该子 Agent 负责什么领域、何时该派给它）、一个**工具子集**（该领域所需工具，是全量工具集的切片而非全部）、以及一段**专用 system prompt**。`SubAgent` MUST 复用既有 `AgentLoop` 在一段**独立上下文**里跑一次 mini TAO 循环并返回最终文本；MUST NOT 重写业务逻辑或反向依赖 `api/`。子 Agent 的上下文与主 Agent 上下文相互隔离：子 Agent 看不到主 Agent 的其它工具，主 Agent 也不直接看到子 Agent 的中间步骤，仅得到其汇总结果。

#### Scenario: 子 Agent 暴露四要素

- **WHEN** 主 Agent 或测试读取任一已实现子 Agent
- **THEN** 该子 Agent 暴露非空 `name`、非空 `description`、一个非空的工具子集、以及一段非空 system prompt

#### Scenario: 子 Agent 在独立上下文跑 mini 循环

- **WHEN** 以一个任务字符串运行某子 Agent
- **THEN** 它构造一个仅绑定自身工具子集的 `AgentLoop`，在独立消息上下文里跑 TAO 循环，并返回最终文本回复

#### Scenario: 子 Agent 上下文与主 Agent 隔离

- **WHEN** 子 Agent 在其循环中产生多步工具调用与中间结果
- **THEN** 这些中间步骤不进入主 Agent 上下文，主 Agent 仅收到子 Agent 的最终汇总文本

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

### Requirement: delegate 工具与主 Agent 自主派生

系统 SHALL 提供一个 `delegate` 工具（薄封装的编排型工具），其入参经 Pydantic 校验，至少含目标子 Agent 标识与任务描述。主 Agent（顶层 `AgentLoop`）SHALL 通过调用 `delegate` 工具**自主决定**把任务交给哪个子 Agent，而非由开发者用 `if category == ...` 硬编码路由。`delegate` 分发时 MUST 把任务转交给对应 `SubAgent` 执行，并把其汇总结果作为工具结果回灌主 Agent 上下文。目标子 Agent 标识非法时 MUST 返回结构化错误而非崩溃。主 Agent 的 system prompt MUST 显式列出可派生的子 Agent 及其职责（显式优于隐式）。

#### Scenario: 主 Agent 据任务派生对应子 Agent

- **WHEN** 用户输入是一个预约请求，主 Agent 决定调用 `delegate` 指向 `appointment` 子 Agent
- **THEN** `delegate` 把任务交给 `appointment` 子 Agent 执行，其结果作为工具结果回灌主 Agent，主 Agent 据此产出最终回复

#### Scenario: 派生标识非法时返回结构化错误

- **WHEN** `delegate` 被调用时传入一个不存在的子 Agent 标识
- **THEN** 返回带错误理由的结构化结果，不崩溃主循环，主 Agent 可据此改派或回复

#### Scenario: 不再硬编码路由

- **WHEN** 审视请求编排路径
- **THEN** 选择哪个子 Agent 由主 Agent 经 `delegate` 工具调用决定，代码中不存在按意图分类的 `if/else` 路由分支
