## ADDED Requirements

### Requirement: 候选可按时间窗筛选

triage 甄别 SHALL 支持按**墙钟时间窗**筛选候选（如「只看某时刻之后的 trace」），使「这一周新增了哪些坏 case」可直接回答，而不必人工翻阅整个 trace 目录。筛选 MUST 基于 span 的墙钟起始时刻；对**不带**墙钟字段的历史 trace 记录，筛选行为 MUST 明确且不静默丢弃——系统 SHALL 或将其一律纳入、或明确报告被跳过的条数，MUST NOT 让它们无声消失。

#### Scenario: 按时间窗筛出新增候选

- **WHEN** trace 目录同时含指定时刻之前与之后的运行记录，且指定该时刻为下界
- **THEN** 只有该时刻之后的 trace 参与甄别，之前的不出现在候选清单中

#### Scenario: 无墙钟字段的历史 trace 不被静默丢弃

- **WHEN** 对同时含带/不带墙钟字段的 trace 目录施加时间窗筛选
- **THEN** 不带该字段的记录要么被纳入、要么在输出中被明确计数报告，MUST NOT 无提示地消失

## MODIFIED Requirements

### Requirement: 从持久化 trace 半自动甄别坏 case

系统 SHALL 提供一个 triage 流程，从落盘的 trace 文件读入运行记录，依据**已有客观信号**给每条 trace 标注「疑似坏」候选状态。可用信号 MUST 至少包含：护栏耗尽、打转、循环达到 `max_steps` 而未产出终态回复、span 中出现工具调用异常、**工具超时**（loop 级中断与 service 级结构化 `error_kind` 两条路径均须覆盖）。甄别 MUST 为纯函数式判定（给定一组 span / trace 记录即可离线确定地得出候选清单），MUST NOT 触网、MUST NOT 调用 LLM。甄别只产出「候选」，MUST NOT 自行判定真值或自动改写评估集。

读入 trace 记录时，排序与时间筛选 SHALL 优先使用 span 的墙钟起始时刻；该字段缺失时 MUST 回退到文件行序（同一 tracer 按完成顺序追加，与按 start 排序一致）。**已落盘的历史 trace 文件 MUST 仍可被正常加载**——引入墙钟字段 MUST NOT 使既有真实流量记录失效。

> 口径修正：原信号集列有「最终回复带 `[ERROR]` 前缀」。该前缀是遗留 `agents/` 路径的产物，当前生产走的 harness `AgentLoop` 只产 `[THOUGHT]`/`[REPLY]`，故该信号永不命中——原文属规格要求了一个实现刻意不做的信号。此处按真实落点重述。

#### Scenario: 命中失控信号的 trace 被标为候选

- **WHEN** 对一批含「达到 max_steps」「工具异常」「工具超时」的 trace 跑甄别
- **THEN** 这些 trace 被列入「疑似坏」候选清单，未命中任何信号的 trace 不在候选中

#### Scenario: 甄别可离线确定性测试

- **WHEN** 在内存中构造若干带/不带失控信号的 span 记录并跑甄别
- **THEN** 候选判定结果确定可复现，全程不发起网络调用、不调用 LLM

#### Scenario: 历史 trace 文件仍可加载

- **WHEN** 对不含墙钟字段的既有 trace 文件跑甄别
- **THEN** 该文件被正常解析，span 顺序回退按文件行序确定，甄别结果与引入墙钟字段前一致

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
