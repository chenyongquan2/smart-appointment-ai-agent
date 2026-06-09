## ADDED Requirements

### Requirement: 意图分类返回受约束的枚举

系统 SHALL 通过结构化输出（function calling / `with_structured_output`）将用户或工作人员的消息分类为五个意图之一：`appointment`、`query`、`pay`、`statistics`、`other`。分类结果 MUST 由 Pydantic schema（枚举类型）约束，使模型在协议层只能返回合法值，禁止依赖 `strip().lower()` + 白名单这类字符串后处理。

#### Scenario: 合法预约消息被分类为 appointment
- **WHEN** 用户输入"请帮我预约今天下午3点的服务1小时"
- **THEN** 系统返回意图 `appointment`

#### Scenario: 模型协议层保证枚举合法性
- **WHEN** 对任意输入调用分类
- **THEN** 返回值必为五个枚举之一，且不经过 `strip().lower()` 白名单兜底逻辑（该逻辑被移除）

#### Scenario: 对外签名向后兼容
- **WHEN** 既有调用方调用 `classify_task(task)`
- **THEN** 返回类型仍为 `str`（五类之一），调用方无需改动

### Requirement: 分类异常时安全降级

当 LLM 调用本身失败（网络/超时/解析异常）时，系统 SHALL 记录结构化错误日志并安全降级为 `other`，不得让异常向上冒泡使整个请求崩溃。

#### Scenario: LLM 调用抛异常
- **WHEN** 分类过程中 LLM 调用抛出异常
- **THEN** 系统记录错误日志并返回 `other`，不抛出异常
