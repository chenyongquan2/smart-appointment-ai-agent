## ADDED Requirements

### Requirement: Skill 声明结构

系统 SHALL 提供一个 `Skill` 抽象，定义在 `harness/skills/` 下（一个概念一个文件），声明：唯一 `name`、面向加载决策的 `description`（说明该 skill 提供什么能力、何时该加载）、以及该 skill 注入子 Agent 上下文的**内容**（如补充提示片段或可用工具引用）。Skill MUST 为可复用能力的薄声明，不重写业务逻辑。对齐 Claude Code skills 机制：skill 默认不常驻，仅在被判定相关时按需加载。

#### Scenario: Skill 暴露声明要素

- **WHEN** 注册中心或测试读取任一 skill
- **THEN** 该 skill 暴露非空 `name`、非空 `description`、以及可注入上下文的内容

### Requirement: SkillRegistry 按需加载

系统 SHALL 提供一个 `SkillRegistry`，支持注册 skill、按 `name` 查找、并按任务/描述匹配**按需加载**相关 skill（而非全量常驻注入）。注册重名 skill MUST 报错。加载 MUST 是显式可观测的（可被测试断言哪些 skill 被加载、哪些未被加载）。当没有 skill 匹配时，MUST 返回空集合而非报错。

#### Scenario: 按描述匹配加载相关 skill

- **WHEN** 子 Agent 以一个与某 skill 描述相关的任务向 `SkillRegistry` 请求加载
- **THEN** registry 返回该匹配的 skill，未匹配的其它 skill 不被加载

#### Scenario: 无匹配时返回空集

- **WHEN** 以一个与任何已注册 skill 都不相关的任务请求加载
- **THEN** registry 返回空集合，不报错、不注入任何 skill

#### Scenario: 重名注册报错

- **WHEN** 向 `SkillRegistry` 注册一个 `name` 已存在的 skill
- **THEN** registry 抛出明确错误，拒绝覆盖
