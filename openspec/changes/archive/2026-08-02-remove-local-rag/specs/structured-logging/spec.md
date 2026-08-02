## MODIFIED Requirements

### Requirement: agents 与 api 不得用 print 输出

`agents/` MUST NOT 通过 `print` 向 stdout 输出运行信息;一切运行/调试/错误输出 MUST 经 `logging.getLogger(__name__)` 取得的 logger。

原文并列点名的 `api/knowledge.py` 随本地 RAG 一并删除（change `remove-local-rag`），故从约束对象中移除；约束本身不变，仍适用于 `agents/` 以及后续新增的 `api/` 模块。

#### Scenario: 无残留 print
- **WHEN** 检索 `agents/`(排除测试与 `__pycache__`)
- **THEN** 不存在 `print(` 调用

#### Scenario: 日志级别语义正确
- **WHEN** 替换原 `print`
- **THEN** 启动/状态/路由类用 `debug`/`info`,失败类用 `error`(语义与原意一致,不改控制流)
