## ADDED Requirements

### Requirement: LLM-as-judge 评回复质量（pointwise 二元）

评估 SHALL 提供一个 LLM-as-judge 对 agent 最终回复做**回复质量**裁决。judge SHALL 用结构化输出返回二元裁决 `{pass: bool, reason: str}`，judge MUST 先产出 `reason` 再给 `pass`（先推理后裁决）。judge 调用 SHALL 用 `temperature=0`，且其 LLM SHALL 可注入（便于用 fake judge 离线确定性单测）。

裁决聚合 SHALL 为纯函数：`response_quality` 吃一组裁决产出**质量通过率**（pass 占比）。无任何裁决（未开启 judge 或未捕获回复）时 SHALL 显式标 N/A，MUST NOT 伪造分母。

judge 默认关闭，经 `--judge` 显式开启（judge 为每条用例的额外 LLM 调用）。judge 评的是「回复是否恰当且正确地回应用户请求」的复合判断；RAG 三元组（faithfulness 等）不在本能力范围。

#### Scenario: judge 产出二元裁决并聚合为通过率

- **WHEN** 以 `--judge` 运行，judge 对每条回复返回 `{pass, reason}`
- **THEN** 报告输出回复质量通过率（pass 占比），并对裁决聚合用纯函数计算

#### Scenario: 未开启 judge 时回复质量记 N/A

- **WHEN** 不带 `--judge` 运行
- **THEN** 回复质量指标显式标 N/A，不伪造分母、不计入对错

#### Scenario: judge 调用层可用 fake judge 离线测

- **WHEN** 注入一个脚本化 fake judge LLM 跑 judge 调用层
- **THEN** 不触网即可断言裁决解析与聚合，裁决聚合为纯函数

### Requirement: judge 校准机制与未校准显式标注

评估 SHALL 提供纯函数 `judge_human_agreement(judge_labels, human_labels)`，对二元标注计算 **judge 与人工的一致率与 Cohen's κ**。系统 SHALL 提供一个校准集占位（供人工填真实 pass/fail 标注），且 MUST NOT 伪造人工标注。

在人工校准标注缺失时，回复质量报告 SHALL 显式标注 judge 为「未校准（κ 未测）」，MUST NOT 把未经校准的 judge 结果呈现为可信真值。judge 与 agent 同模型导致的自我偏好风险 SHALL 在文档/报告中作为已知局限说明。

#### Scenario: 算 judge 与人工一致率与 κ

- **WHEN** 给定一组 judge 二元标注与对应的人工二元标注
- **THEN** `judge_human_agreement` 返回一致率与 Cohen's κ（纯函数、可离线断言）

#### Scenario: 缺人工标注时标未校准

- **WHEN** 校准集无人工标注而运行 judge
- **THEN** 报告显式标注 judge「未校准」，不声称其裁决为可信真值
