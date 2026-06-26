## Why

回归门禁（改造 6）的 `GATED_METRICS` 列了三项正确性指标 `{意图分类准确率, 工具调用-F1, 槽位抽取完整率}`，但 `槽位抽取完整率` 至今**结构性恒 N/A**——`evals/run_evals.py` 把 `actual_slots` 硬写为 `None`、且 `cases.jsonl` 无用例标 `expected_slots`。结果门禁**今天实守只有 2 项**。`slot_completeness` 指标本身（`evals/metrics.py`）早已完整实现，所缺的只是「采集接线 + 用例标注」这最后一公里。端到端真跑已在 `cap.tool_calls` 里采到了工具调用的 args（`agent_capture.py`），槽位就藏在这些 args 里——接线成本低、收益是门禁从守 2 项升到 3 项。

## What Changes

- **接线 `actual_slots`**：新增一个**纯函数**，把 `CaptureResult.tool_calls` 各工具调用的 args 合并还原为一份扁平的「槽位 dict」（键归一到槽位口径：`start_time / duration / project / preference / gender / technician`）。`run_evals.py` 用它替换当前硬写的 `actual_slots=None`。
- **指标改存在性口径**（实现中实测后修订，见 design D8）：`slot_completeness` 由「精确值匹配」改为「**存在性完整率**」——只看期望槽位的键是否被抽出，不比精确值。因实测发现当前 agent 抽出的槽位值为自由文本且不规范（`gender='男'`、`start_time` 可能算错日期），精确匹配会令指标几乎恒 miss、失去意义。`expected_slots` 随之重解释为「期望被抽到的槽位**键集合**」（dict 形式，值仅作说明）。
- **标注 `expected_slots`**：给 `cases.jsonl` 中若干预约类用例补标 `expected_slots`（与已有 `expected_tool_args` 区分口径，见 design）。
- **确定性单测**：还原纯函数加离线单测（对齐项目「比对/序列化为纯函数、可离线确定性单测」的惯例，参考 `tests/test_eval_gate.py`），覆盖跨工具合并、同名槽位冲突、哨兵值（`未知`/`无`）判定等边界。
- **报告与文档同步**：接线后报告的「门禁今天实守 N 项」从 `2` 变 `3`；同步 `evals/README.md`、`docs/agent-eval-fieldguide.md` 中「今天实守 2 项 / 槽位结构性恒 N/A」的措辞，如实反映新状态，不夸大。

## Capabilities

### New Capabilities
<!-- 无新增能力——本变更是对既有 eval-harness 能力的接线兑现。 -->

### Modified Capabilities
- `eval-harness`: 修改「诚实的比对语义」中关于 `槽位抽取完整率` **结构性恒 N/A** 的既有需求——`actual_slots` 接线、用例补标 `expected_slots` 后，该指标 SHALL 产出真值（非 N/A），门禁实守指标数 SHALL 由 2 升至 3；并新增对「`actual_slots` 如何从工具调用 args 还原」的需求（合并规则、冲突处理、哨兵值判定）。

## Impact

- **代码**：`evals/run_evals.py`（接线点 `actual_slots`）；新增/修改一个槽位还原纯函数（落点在 `evals/`，候选 `evals/metrics.py` 或新模块）；`evals/cases.jsonl`（补标 `expected_slots`）。
- **测试**：新增槽位还原纯函数的确定性单测。
- **基线**：接线后 `slot_completeness` 由 N/A 变真值，需用 `--update-baseline` **重定基线**纳入该指标快照（一次性，配 `--samples 3`）。
- **文档**：`evals/README.md`、`docs/agent-eval-fieldguide.md` 措辞同步。
- **不动**：`slot_completeness` 指标算法、门禁比对逻辑、`GATED_METRICS` 集合本身均不改——本变更只补上让该指标「跑出真数」的输入。
