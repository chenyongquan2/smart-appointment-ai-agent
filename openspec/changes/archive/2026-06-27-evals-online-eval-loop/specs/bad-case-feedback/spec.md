## ADDED Requirements

### Requirement: 从持久化 trace 半自动甄别坏 case

系统 SHALL 提供一个 triage 流程，从落盘的 trace 文件读入运行记录，依据**已有客观信号**给每条 trace 标注「疑似坏」候选状态。可用信号 MUST 至少包含：循环达到 `max_steps`、span 中出现工具调用异常、最终回复带 `[ERROR]` 前缀、跑满步数的兜底回复。甄别 MUST 为纯函数式判定（给定一组 span / trace 记录即可离线确定地得出候选清单），MUST NOT 触网、MUST NOT 调用 LLM。甄别只产出「候选」，MUST NOT 自行判定真值或自动改写评估集。

#### Scenario: 命中失控信号的 trace 被标为候选

- **WHEN** 对一批含「达到 max_steps」「工具异常」「回复带 [ERROR]」的 trace 跑甄别
- **THEN** 这些 trace 被列入「疑似坏」候选清单，未命中任何信号的 trace 不在候选中

#### Scenario: 甄别可离线确定性测试

- **WHEN** 在内存中构造若干带/不带失控信号的 span 记录并跑甄别
- **THEN** 候选判定结果确定可复现，全程不发起网络调用、不调用 LLM

### Requirement: 人审标注并回灌 evals/cases.jsonl

系统 SHALL 提供一条人审闸门下的回灌通路：从候选 trace 还原出标注草稿（含 `input` 与观测到的工具/槽位/回复），由人工编辑确认 `expected_intent` / `expected_tools` / `expected_tool_args` / `expected_slots`，产物 MUST 与 `evals/cases.jsonl` 既有用例同构（可被 `run_evals.py` 的 `load_cases` 直接加载）。回灌时 MUST 按 `input` 规范化**去重**——已存在等价用例的候选 MUST NOT 重复追加；新追加用例 SHALL 携带 `"source":"online"` 溯源标记。系统 MUST NOT 在回灌后自动重定基线（re-baseline）；回灌完成后 SHALL 打印提醒「用例集已变更，需运行 `--update-baseline` 重定基线」，把基线变更交还人审（不绕过回归门禁）。

#### Scenario: 人审通过的候选追加进用例集

- **WHEN** 人工对一条候选完成 `expected_*` 标注并确认回灌
- **THEN** 一条与 `cases.jsonl` 同构、带 `"source":"online"` 的用例被追加，且能被 `load_cases` 正常加载

#### Scenario: 重复输入不重复回灌

- **WHEN** 回灌一条 `input` 与已有用例规范化后等价的候选
- **THEN** 该候选 MUST NOT 被追加，回灌流程报告其为「已存在、跳过」

#### Scenario: 回灌后提醒重定基线、不自动改基线

- **WHEN** 完成一次或多次回灌
- **THEN** 系统打印「用例集已变更，需 `--update-baseline`」提醒，且 `evals/baseline.json` 未被自动修改
