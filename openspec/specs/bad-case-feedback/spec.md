# bad-case-feedback Specification

## Purpose
TBD - created by archiving change phase-6-observability. Update Purpose after archive.
## Requirements
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

### Requirement: 从持久化 trace 半自动甄别坏 case

系统 SHALL 提供一个 triage 流程，从落盘的 trace 文件读入运行记录，依据**已有客观信号**给每条 trace 标注「疑似坏」候选状态。可用信号 MUST 至少包含：护栏耗尽、打转、循环达到 `max_steps` 而未产出终态回复、span 中出现工具调用异常、**工具超时**（loop 级中断与 service 级结构化 `error_kind` 两条路径均须覆盖）、**同一工具换参重复调用**（同一 (工具, 身份参数) 组合跨 ≥N 个步骤出现，见 `observability`）。甄别 MUST 为纯函数式判定（给定一组 span / trace 记录即可离线确定地得出候选清单），MUST NOT 触网、MUST NOT 调用 LLM。甄别只产出「候选」，MUST NOT 自行判定真值或自动改写评估集。

读入 trace 记录时，排序与时间筛选 SHALL 优先使用 span 的墙钟起始时刻；该字段缺失时 MUST 回退到文件行序（同一 tracer 按完成顺序追加，与按 start 排序一致）。**已落盘的历史 trace 文件 MUST 仍可被正常加载**——引入墙钟字段 MUST NOT 使既有真实流量记录失效。

> 口径修正（change `fix-trace-triage-blindspots`）：原信号集列有「最终回复带 `[ERROR]` 前缀」。该前缀是遗留 `agents/` 路径的产物，当前生产走的 harness `AgentLoop` 只产 `[THOUGHT]`/`[REPLY]`，故该信号永不命中——原文属规格要求了一个实现刻意不做的信号。此处按真实落点重述。

新增信号 MUST NOT 降低候选清单的信噪比：真实数据中存在的正当模式（逐维度枚举、换检索策略、多意图并行检索）MUST NOT 因「同工具换参重复」信号进入候选。

#### Scenario: 命中失控信号的 trace 被标为候选

- **WHEN** 对一批含「达到 max_steps」「工具异常」「工具超时」「同工具换参重复」的 trace 跑甄别
- **THEN** 这些 trace 被列入「疑似坏」候选清单，未命中任何信号的 trace 不在候选中

#### Scenario: 正当检索模式不进候选

- **WHEN** 对含「逐维度枚举」「换检索策略」「多意图并行检索」的 trace 跑甄别
- **THEN** 这些 trace MUST NOT 因「同工具换参重复」信号进入候选清单

#### Scenario: 甄别可离线确定性测试

- **WHEN** 在内存中构造若干带/不带失控信号的 span 记录并跑甄别
- **THEN** 候选判定结果确定可复现，全程不发起网络调用、不调用 LLM

#### Scenario: 历史 trace 文件仍可加载

- **WHEN** 对不含墙钟字段的既有 trace 文件跑甄别
- **THEN** 该文件被正常解析，span 顺序回退按文件行序确定，甄别结果与引入墙钟字段前一致

### Requirement: 候选可按时间窗筛选

triage 甄别 SHALL 支持按**墙钟时间窗**筛选候选（如「只看某时刻之后的 trace」），使「这一周新增了哪些坏 case」可直接回答，而不必人工翻阅整个 trace 目录。时间窗入参 MUST 自带时区信息（UTC 或显式偏移），MUST NOT 按本机时区推测裸时间串。筛选 MUST 基于 span 的墙钟起始时刻，并 MUST 按 trace 组而非单个 span 施加（逐 span 筛会在窗口边界丢掉 root span，导致候选的 `input` 丢失）。对**不带**墙钟字段的历史 trace 记录，系统 MUST 将其一律纳入并明确报告其条数，MUST NOT 让它们无声消失。

#### Scenario: 按时间窗筛出新增候选

- **WHEN** trace 目录同时含指定时刻之前与之后的运行记录，且指定该时刻为下界
- **THEN** 只有该时刻之后的 trace 参与甄别，之前的不出现在候选清单中

#### Scenario: 拒绝无时区的时间串

- **WHEN** 时间窗入参是不带时区的裸时间串
- **THEN** 系统报错并说明需带时区，MUST NOT 按本机时区推测

#### Scenario: 无墙钟字段的历史 trace 不被静默丢弃

- **WHEN** 对同时含带/不带墙钟字段的 trace 目录施加时间窗筛选
- **THEN** 不带该字段的记录被纳入，且其条数在输出中被明确计数报告

### Requirement: 人审标注并回灌 evals/cases.jsonl

系统 SHALL 提供一条人审闸门下的回灌通路：从候选 trace 还原出标注草稿（含 `input` 与观测到的工具/槽位/回复），由人工编辑确认 `expected_intent` / `expected_tools` / `expected_tool_args` / `expected_slots`，产物 MUST 与 `evals/cases.jsonl` 既有用例同构（可被 `run_evals.py` 的 `load_cases` 直接加载）。回灌时 MUST 按 `input` 规范化**去重**——已存在等价用例的候选 MUST NOT 重复追加；新追加用例 SHALL 携带 `"source":"online"` 溯源标记。系统 MUST NOT 在回灌后自动重定基线（re-baseline）；回灌完成后 SHALL 打印提醒「用例集已变更，需运行 `--update-baseline` 重定基线」，把基线变更交还人审（不绕过回归门禁）。

回灌产物 MUST NOT 携带 `user_id` 或任何提交者标识：`cases.jsonl` **进版本库**，而 trace 目录不进。字段白名单 MUST 由测试钉住，使其不因后续扩字段而意外放行个人标识。

#### Scenario: 人审通过的候选追加进用例集

- **WHEN** 人工对一条候选完成 `expected_*` 标注并确认回灌
- **THEN** 一条与 `cases.jsonl` 同构、带 `"source":"online"` 的用例被追加，且能被 `load_cases` 正常加载

#### Scenario: 重复输入不重复回灌

- **WHEN** 回灌一条 `input` 与已有用例规范化后等价的候选
- **THEN** 该候选 MUST NOT 被追加，回灌流程报告其为「已存在、跳过」

#### Scenario: 回灌后提醒重定基线、不自动改基线

- **WHEN** 完成一次或多次回灌
- **THEN** 系统打印「用例集已变更，需 `--update-baseline`」提醒，且 `evals/baseline.json` 未被自动修改

#### Scenario: 回灌产物不含提交者标识

- **WHEN** 从一条 root span 带 `user_id` 的候选回灌用例
- **THEN** 追加进 `cases.jsonl` 的用例不含 `user_id` 或任何提交者标识字段

