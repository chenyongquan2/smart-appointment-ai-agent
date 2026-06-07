## ADDED Requirements

### Requirement: 测试套件离线确定性通过

`uv run pytest` MUST 在**无 API key、无网络**条件下以退出码 0 完成,不得有 `failed`。允许的非通过状态仅为**有明确理由标注的 `xfail`**。该套件作为重构 `agents/` → `harness/` 前的黄金样本与回归防线。

#### Scenario: 无 key 离线运行全绿
- **WHEN** 在未配置任何 `*_API_KEY`、断网的环境执行 `uv run pytest`
- **THEN** 进程退出码为 0,输出中 `failed` 计数为 0

#### Scenario: 非通过项必须可追溯
- **WHEN** 套件中存在任何 `xfail` 项
- **THEN** 每个 `xfail` MUST 带 `reason`,说明为何隔离(API 错位 / 待重构),不得是裸 skip/xfail

### Requirement: async 测试可被收集执行

被 `@pytest.mark.asyncio` 标记的测试 MUST 被 pytest 真正收集并以协程方式运行,不得退化为"未知 mark"警告而被跳过。

#### Scenario: async 测试实际执行
- **WHEN** 运行 `test_task_classification_agent.py` 中标 `asyncio` 的测试
- **THEN** 该测试体内的 `await` 被执行,断言被求值(而非产生 `PytestUnknownMarkWarning`)

### Requirement: classification 测试不依赖真实 LLM

`test_task_classification_agent.py` MUST 通过注入假 LLM 运行,使结果确定、可离线复现,不得发起真实模型调用。

#### Scenario: LLM 被假实现替换
- **WHEN** 运行 classification 测试
- **THEN** `config.model_provider.create_chat_model` 返回的对象为受测试控制的假实现,测试期间无任何真实网络模型调用发生

### Requirement: phantom 测试被隔离而非误判为回归

`test_user_behavior_agent.py` 中断言了**当前实现不存在的 API**的测试 MUST 以 `xfail` 隔离并附理由,不得通过实现 phantom API 来"凑绿",也不得作为 `failed` 计入。

#### Scenario: phantom 测试以 xfail 计入
- **WHEN** 运行 user_behavior 中断言不存在 API 的测试
- **THEN** 它们被记为 `xfailed`,理由指明"断言未实现 API / agents 待重构",`failed` 计数不增加
