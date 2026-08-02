# structured-logging Specification

## Purpose

统一应用的日志输出:以集中的初始化入口产出单行结构化 JSON 日志,消除 `agents/` 与 `api/knowledge.py` 中的裸 `print`,在不改变业务逻辑的前提下提升可观测性与可解析性。

## Requirements

### Requirement: 统一结构化 JSON 日志

应用 MUST 提供一个集中的日志初始化入口,使根 logger 以**单行 JSON** 输出,每条至少含 `timestamp`、`level`、`logger`(名称)、`message` 字段;`app.py` 启动时 MUST 调用它替代裸 `logging.basicConfig`。

调用方经 `extra={...}` 传入的业务字段 MUST 一并输出。核心字段（`timestamp` / `level` / `logger` / `message`）MUST NOT 被同名的 `extra` 键覆盖。`extra` 中不可 JSON 序列化的值 MUST 降级为其字符串表示，MUST NOT 让日志记录本身抛异常。

理由：此前 formatter 只取固定四项、把 `extra` 全部丢弃，于是全应用写的结构化字段等于白写——日志看着"结构化"，真要查「哪个 session、哪个 event_id、投递为何失败」时一个字段都没有。而 Channel 与 executor 的排障完全依赖这些字段（本变更实测中就因此拿不到会话键的诊断信息，只能改从数据库反查）。

「不可序列化即降级」是硬要求而非便利：`extra` 里可能带枚举、`asyncio.Task`（如 gateway 传的 ack task）等对象，若序列化失败就抛异常，等于把「记录一次失败」变成「再制造一次失败」——而这往往正发生在最需要日志的时刻。

#### Scenario: 启动后日志为 JSON
- **WHEN** 应用启动并产生任意一条日志
- **THEN** 该行可被解析为 JSON,且含 `timestamp`/`level`/`logger`/`message` 字段

#### Scenario: 错误日志携带堆栈
- **WHEN** 在 `except` 块中记录失败
- **THEN** 以 `level=ERROR` 记录,并包含异常信息(`exc_info`),而非仅一句文本

#### Scenario: extra 业务字段被输出

- **WHEN** 以 `logger.info("已提交任务", extra={"session_id": ..., "event_id": ...})` 记录
- **THEN** 输出的 JSON 中含 `session_id` 与 `event_id` 字段，且不含 `LogRecord` 的内部属性（`pathname` / `lineno` / `args` 等）

#### Scenario: 核心字段不被 extra 顶掉

- **WHEN** `extra` 中含与核心字段同名的键（如 `logger`）
- **THEN** 输出中该核心字段仍为框架赋予的值，不被覆盖

#### Scenario: 不可序列化的字段不致失败

- **WHEN** `extra` 中含不可 JSON 序列化的对象
- **THEN** 该字段以其字符串表示输出，记录过程不抛异常

### Requirement: agents 与 api 不得用 print 输出

`agents/` MUST NOT 通过 `print` 向 stdout 输出运行信息;一切运行/调试/错误输出 MUST 经 `logging.getLogger(__name__)` 取得的 logger。

原文并列点名的 `api/knowledge.py` 随本地 RAG 一并删除（change `remove-local-rag`），故从约束对象中移除；约束本身不变，仍适用于 `agents/` 以及后续新增的 `api/` 模块。

#### Scenario: 无残留 print
- **WHEN** 检索 `agents/`(排除测试与 `__pycache__`)
- **THEN** 不存在 `print(` 调用

#### Scenario: 日志级别语义正确
- **WHEN** 替换原 `print`
- **THEN** 启动/状态/路由类用 `debug`/`info`,失败类用 `error`(语义与原意一致,不改控制流)

### Requirement: 不引入行为回归

本次仅替换输出方式,MUST NOT 改变业务逻辑、控制流或函数签名;现有测试套件 MUST 保持通过。

#### Scenario: 测试仍全绿
- **WHEN** 替换完成后运行 `uv run pytest`
- **THEN** 结果不劣于改前(`failed=0`,xfailed 计数不变)
