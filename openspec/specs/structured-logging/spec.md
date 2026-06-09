# structured-logging Specification

## Purpose

统一应用的日志输出:以集中的初始化入口产出单行结构化 JSON 日志,消除 `agents/` 与 `api/knowledge.py` 中的裸 `print`,在不改变业务逻辑的前提下提升可观测性与可解析性。

## Requirements

### Requirement: 统一结构化 JSON 日志

应用 MUST 提供一个集中的日志初始化入口,使根 logger 以**单行 JSON** 输出,每条至少含 `timestamp`、`level`、`logger`(名称)、`message` 字段;`app.py` 启动时 MUST 调用它替代裸 `logging.basicConfig`。

#### Scenario: 启动后日志为 JSON
- **WHEN** 应用启动并产生任意一条日志
- **THEN** 该行可被解析为 JSON,且含 `timestamp`/`level`/`logger`/`message` 字段

#### Scenario: 错误日志携带堆栈
- **WHEN** 在 `except` 块中记录失败
- **THEN** 以 `level=ERROR` 记录,并包含异常信息(`exc_info`),而非仅一句文本

### Requirement: agents 与 api 不得用 print 输出

`agents/` 与 `api/knowledge.py` MUST NOT 通过 `print` 向 stdout 输出运行信息;一切运行/调试/错误输出 MUST 经 `logging.getLogger(__name__)` 取得的 logger。

#### Scenario: 无残留 print
- **WHEN** 检索 `agents/`(排除测试与 `__pycache__`)与 `api/knowledge.py`
- **THEN** 不存在 `print(` 调用

#### Scenario: 日志级别语义正确
- **WHEN** 替换原 `print`
- **THEN** 启动/状态/路由类用 `debug`/`info`,失败类用 `error`(语义与原意一致,不改控制流)

### Requirement: 不引入行为回归

本次仅替换输出方式,MUST NOT 改变业务逻辑、控制流或函数签名;现有测试套件 MUST 保持通过。

#### Scenario: 测试仍全绿
- **WHEN** 替换完成后运行 `uv run pytest`
- **THEN** 结果不劣于改前(`failed=0`,xfailed 计数不变)
