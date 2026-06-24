## Why

评估至今全是「能用 `==`/`set` 判」的客观指标（意图、工具调用）。本项目最大能力缺口是**没有评回复质量**——「这条回复是否恰当、有帮助、正确」无法用客观比对判定（教材 §6）。改造 4 引入 **LLM-as-judge**，对 agent 最终回复做质量裁决，补上这块缺口。难点：judge 本身是 LLM（非确定、要触网），不能毁掉改造 1-3 一路守住的「指标纯函数、可离线确定性单测」根基；且**没校准过的 judge 只是又一个意见**，不能当真值。

## What Changes

- **judge 调用层（可注入）**：新增 `evals/judge.py`——`judge_response(input, reply, llm)` 用 **structured output** 返回二元裁决 `{pass: bool, reason: str}`，**reason 先于 pass**（先推理后裁决）、`temperature=0`。llm 可注入，故可用 fake judge 离线确定性测（复刻改造 1 的「调用层触网 / 聚合层纯函数」模式）。
- **裁决聚合层（纯函数）**：`evals/metrics.py` 新增 `response_quality(verdicts)` → 质量通过率（无裁决时 N/A，不伪造分母）。
- **回复采集**：`evals/agent_capture.py` 在采工具调用之外，**同时surface agent 最终回复文本**（judge 的输入）。
- **校准机制（建好、数据留空，不造假）**：新增纯函数 `judge_human_agreement(judge_labels, human_labels)` → 一致率 + **Cohen's κ**（二元最干净）；新增 `evals/calibration.jsonl` 占位供**人工**填真实 pass/fail；**人工标注填入前，报告显式标 judge「未校准（κ 未测）」**。
- **开关**：`--judge`（默认关，judge = 每条额外 LLM 调用，按需开）。
- **已知局限**：judge 与 agent 同 provider/模型 → **自我偏好**风险，显式列局限（理想解换裁判模型，单 provider 暂不可行）；长度偏差靠 rubric 压、不保证根除。

## Capabilities

### New Capabilities
<!-- 无新增能力；修改既有 eval-harness -->

### Modified Capabilities
- `eval-harness`: 新增「LLM-as-judge 评回复质量（pointwise 二元 pass/fail）」与「judge 校准机制（一致率 + Cohen's κ）及未校准显式标注」两项能力；judge 调用层可注入、裁决聚合纯函数、结构化裁决，守住离线可测根基。

## Impact

- **源码**：`evals/judge.py`（新，judge 调用层）；`evals/metrics.py`（`response_quality` 聚合 + `judge_human_agreement` 校准纯函数 + 报告渲染「未校准」标注）；`evals/agent_capture.py`（surface 最终回复）；`evals/run_evals.py`（`--judge` 开关 + 每条调 judge）。
- **数据**：`evals/calibration.jsonl`（占位，供人工填真实标注）。
- **测试**：`tests/`（fake judge 驱动 judge 调用层、`response_quality` 聚合、κ 计算、未校准标注的离线确定性测）。
- **与改造 3 组合**：judge 自身非确定性可被 `--samples` 的 mean±CI 量化。
- **显式不在范围**：pairwise + 位置互换（→ 改造 6，需基线回复）；RAG 三元组 faithfulness/context-relevance/answer-relevance（→ 改造 5，需检索上下文）；换不同裁判模型消自我偏好（单 provider）；伪造人工标注（绝不）；基线持久化/阈值阻断（→ 改造 6）。
