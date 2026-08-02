## ADDED Requirements

### Requirement: 领域包的结构与内容

系统 SHALL 把「领域」收敛为一个**可装载的包**，每个领域包 SHALL 提供且仅提供以下五样域绑定的东西：

1. **工具集**——该域可供模型调用的 `Tool` 定义；
2. **子 Agent 集**——该域的 `SubAgent` 定义（各自持有工具子集）；
3. **系统提示**——该域的人设、职责边界与红线文本；
4. **权限策略**——该域的危险操作判定策略；
5. **评估数据**——该域的用例集与基线所在目录。

领域包 MUST NOT 包含域无关的运行时机制（TAO 循环、`ToolRegistry` / `SubAgentRegistry` 结构、记忆分层、护栏、Tracer、系统提示的拼接逻辑、评估运行器）。判据是一句话：**这段代码换成另一个域还成立吗？** 成立即属域无关运行时，MUST 留在 `harness/` 或 `evals/`。

#### Scenario: 领域包提供齐五样东西

- **WHEN** 装载任一领域包
- **THEN** 得到的领域对象含工具集、子 Agent 集、系统提示、权限策略、评估数据目录五项，缺一即为装载失败

#### Scenario: 域无关机制不随域走

- **WHEN** 检查 `harness/` 与 `evals/`
- **THEN** 其中不存在任何具体领域的工具定义、子 Agent 定义或人设文本；`ToolRegistry`、`SubAgentRegistry`、系统提示拼接函数、评估运行器均保持域无关

### Requirement: 按配置装载领域，运行时对域无知

系统 SHALL 由**配置**决定装载哪个领域包（环境变量 `AGENT_DOMAIN`，缺省为 `appointment`），使同一份代码可跑不同域的实例。

运行时代码 MUST NOT 出现按域名分支的逻辑（`if domain == "oncall"` 之类）。运行时只消费领域对象声明的内容，不得知道自己正跑在哪个域上。

装载未知域名时 MUST 抛出明确错误并列出可选域名，MUST NOT 静默回落到缺省域——静默回落会让配置写错表现为"跑起来了但装错了域"，比启动失败危险得多。

#### Scenario: 缺省装载预约域

- **WHEN** 未设置 `AGENT_DOMAIN` 即启动
- **THEN** 装载 `appointment` 域，行为与领域包化之前完全一致

#### Scenario: 配置切换领域无需改代码

- **WHEN** 设置 `AGENT_DOMAIN` 为另一个已注册的域名
- **THEN** 运行时装载该域的五样东西，`harness/` 与 `evals/` 的代码 MUST 无需任何改动

#### Scenario: 未知域名启动即失败

- **WHEN** `AGENT_DOMAIN` 为未注册的域名
- **THEN** 抛出明确错误并列出全部可选域名，MUST NOT 回落到缺省域

#### Scenario: 运行时不含域名分支

- **WHEN** 检索 `harness/`、`evals/`、`executor/`、`channels/`
- **THEN** 不存在按具体域名分支的条件判断

### Requirement: 权限策略随域声明并接入分发

每个领域包 SHALL 显式声明自己的权限策略，且该策略 MUST 被接入 `ToolRegistry` 的分发路径，使危险工具在执行前真正经过判定。

本需求存在的理由：权限闸门此前虽已实现，却**从未被接入生产路径**（实际走 `allow_all` 默认）。一条从未被验证过的接线，等于没有——若到某个域声明只读红线时才发现分发根本不查策略，红线就只是纸面约定。

#### Scenario: 域声明的策略确实生效

- **WHEN** 装载的领域包声明了一个拒绝某危险工具的策略，随后分发该工具
- **THEN** 该工具的 handler MUST NOT 被执行，分发返回带理由的结构化拒绝结果

#### Scenario: 预约域维持既有判定结果

- **WHEN** 装载 `appointment` 域并分发其任一工具（含危险的 `create_appointment`）
- **THEN** 判定结果与领域包化之前完全一致（放行），即本次接线不改变任何既有行为
