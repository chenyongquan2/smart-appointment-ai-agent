## ADDED Requirements

### Requirement: 坏 case 落库

系统 SHALL 提供一个 `bad_cases` 持久化表与对应 Repository（遵循 `db/repositories/` 既有模式），用于记录失败或用户纠正的 case。每条记录 MUST 含：`kind`（`failure` 或 `correction`）、`user_input`、`expected`（期望，可空）、`actual`（实际，可空）、`created_at`，并 MAY 关联 `trace_id` 与 `session_id`、携带 `extra`（JSON）。该表 MUST 为新增独立表，MUST NOT 改动既有业务表的语义或结构。

#### Scenario: 写入一条失败 case

- **WHEN** 调用 Repository 写入一条 `kind=failure` 的 case（含 user_input 与 actual）
- **THEN** 该记录被持久化，可经读取接口取回，且含 `created_at`

#### Scenario: 关联 trace_id 便于复盘

- **WHEN** 写入 case 时提供 `trace_id`
- **THEN** 该 `trace_id` 随记录持久化，可据以与对应 trace 关联复盘

### Requirement: 坏 case 读取接口

Repository SHALL 提供最小读取接口：按时间倒序列出最近 N 条、以及按 `kind` 过滤列出。读取 MUST NOT 自动改写 `evals/cases.jsonl`（增补评估集由人审决定，本能力只负责落库与读取）。

#### Scenario: 列出最近坏 case

- **WHEN** 已写入若干 case 后调用"列出最近 N 条"
- **THEN** 返回按 `created_at` 倒序的至多 N 条记录

#### Scenario: 按 kind 过滤

- **WHEN** 调用按 `kind=correction` 过滤的读取
- **THEN** 仅返回 `kind=correction` 的记录，不含 `failure`

### Requirement: 落库可离线确定性测试

坏 case 的写入与读取 SHALL 可在不触网的条件下用内存/临时 SQLite 做确定性单元测试（参照 `tests/test_conversation_repository.py` 的既有模式）。

#### Scenario: 用临时库测写读

- **WHEN** 在临时/内存 SQLite 上写入再读取坏 case
- **THEN** 写读一致、全程不发起网络调用
