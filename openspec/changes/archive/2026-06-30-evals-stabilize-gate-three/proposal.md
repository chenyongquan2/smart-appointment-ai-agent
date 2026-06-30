## Why

CI 门禁（`evals/run_evals.py --gate`）守 `GATED_METRICS = {意图分类准确率, 工具调用-F1, 槽位抽取完整率}` 三项，但「槽位抽取完整率」依赖预约类用例**真触发工具链**（`actual_slots` 从工具调用 args 还原）。预约子 Agent 对**信息不全的单轮输入**会按系统提示「不臆测下单、先追问」（[harness/subagents/appointment.py:36](../../../harness/subagents/appointment.py#L36)），故工具仅约 1/3 触发；某次跑若所有带 `expected_slots` 的用例都没触发工具，槽位指标 N/A、按 skipped 处理，门禁当次**回落到只守 2 项**。这是教材 §12/§13（改造 8）和 [evals/README.md](../../../evals/README.md) 改造 6 节末尾「诚实保留项」明列的待收口项——门禁实守项数不稳定，削弱回归防护可信度。

## What Changes

- **策展预约类用例**：把带 `expected_slots` 的预约用例改写为**信息齐全的祈使式单轮输入**（时间 + 项目 + 必要槽位俱全、明确下单意图），使保守的子 Agent 倾向「直接办理（触发工具）」而非「追问」，从而让 `actual_slots` 稳定还原出真值。
- **扩充触发样本量**：在 5 类全覆盖与既有口径不变的前提下，适度增补几条信息齐全、带 `expected_slots` 的预约用例，把「某次跑所有相关用例都不触发工具」的概率压到接近零（单条 ~1/3 触发率下，样本越多越稳）。
- **收紧 spec 口径**：在 `eval-harness` 能力中明确——带 `expected_slots` 的预约用例 SHALL 以信息齐全的祈使式表述为主，使「槽位抽取完整率」在常规跑（含 `--samples N`）下稳定非 N/A、门禁稳定实守 3 项；保留对「极端情形下仍可能回落」的诚实标注语义（不假装绝对）。
- **不改业务逻辑**：不动 `services/`、`harness/runtime`、子 Agent 编排与系统提示（CLAUDE.md 禁改清单）；唯一杠杆是**数据集（用例）**。槽位完整率维持「存在性口径」（只看键是否被抽出、不比精确值）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `eval-harness`: 收紧/补充对预约类用例的策展要求，使「槽位抽取完整率」在常规门禁跑下稳定出真值、门禁稳定实守 3 项；既有「基线持久化与回归门禁」「用例标注 expected_slots」等需求的诚实标注语义保持不变。

## Impact

- **数据**：`evals/cases.jsonl`（改写/增补预约类用例，标注 `expected_slots`）。
- **文档**：`evals/README.md`（改造 6 节「诚实保留项」更新为「稳定守 3 项」的现状）、`docs/agent-eval-fieldguide.md`（§12 速查表、§13 改造 8 状态收口）。
- **不影响**：`services/`、`harness/`、`agents/` 业务逻辑与子 Agent 提示；`metrics.py` 指标算法与口径。
- **`baseline.json`**：因新增用例改变评估集，**经人审批准**在新 29 条集上 `--update-baseline --samples 3` 重定基线（刷新意图/工具F1/槽位的稳定均值，使门禁 like-to-like）；非自动、非绕过门禁。
- **验证**：`uv run pytest` 绿；`uv run python evals/run_evals.py --gate --samples 3` 多次观察实守项数稳定为 3。
