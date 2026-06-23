## Why

改造 1 已让 evals 真跑端到端、采集到有序 `[{name, args}]` 的 `actual_tools`，但 `tool_call_correctness` 仍是「集合全等、每条全有或全无」的二元判定——appointment 用例期望 3 个工具，agent 只调到 `find_technician` 就判 0%，误导性强。那个真实的 0% 主要是**颗粒度**问题（全有或全无），不是严格度问题。改造 2 把工具调用比对沿两根独立的轴做严：**颗粒度轴**（per-tool 部分给分）与**严格度轴**（参数 / 顺序），让 0% 变成有信息量的分档指标。

## What Changes

- **颗粒度（部分给分）**：新增 per-tool 的 **召回率 / 精确率 / F1**（按用例宏平均，name 级）——把「3 个里对了 1 个」算成召回 33% 而非 0。
- **严格度·参数级**：新增**参数级 F1**——只对**稳定/类别型参数**（gender / duration / project / technician）做归一化后精确相等，**逐键比**（只比用例标了的键，actual 多出的键忽略）。易变/语义型参数（相对时间 `start_time`、自由文本 `query`/`preference`）**显式不纳入**，语义等价留给改造 4 的 LLM-judge。
- **严格度·序列级**：新增**序列正确率**——expected 作为有序**子序列**匹配 actual（全局按 `span.start` 拍平），容忍多调/重试，天然吃多委派交错。
- **保留对照**：原「完全匹配率」（集合全等、全有或全无）保留作最严对照，报告里与宽松召回并列，一眼看出差距。
- **数据格式**：`expected_tools:[名字]` 不变（其顺序同时驱动集合/部分/序列三种判法）；新增可选 `expected_tool_args: {工具名: {键:值}}`，只标稳定键；缺省即对该用例的参数级档记 N/A（不伪造分母）。**BREAKING**：`tool_call_correctness` 单一指标被一组分档指标取代（影响 `metrics.py` 内部与其单测）。

## Capabilities

### New Capabilities
<!-- 无新增能力；修改既有 eval-harness -->

### Modified Capabilities
- `eval-harness`: 工具调用指标从「单一集合全等正确率」扩为一组分档指标（召回/精确/F1 + 参数级F1 + 序列正确率 + 完全匹配率对照）；每档独立 N/A、不伪造分母；新增可选 `expected_tool_args` 标注（只标稳定键）。

## Impact

- **源码**：`evals/metrics.py`（分档指标计算 + 报告分档渲染）。
- **用例**：`evals/cases.jsonl`（给 6 条 appointment + 2 条多工具 query 补 `expected_tool_args`，只标稳定键）。
- **测试**：`tests/test_eval_metrics.py`（补部分给分 P/R/F1、参数逐键比、子序列匹配、各档 N/A 的离线确定性单测）。
- **保持不变**：采集层（改造 1 的 `actual_tools` 形状）、tracer、真跑路径——改造 2 纯改比对与报告，不动采集。
- **显式不在范围**：参数语义/时间等价（→ 改造 4 LLM-judge）；可交换工具对的精确偏序（→ 改造 8）；基线持久化+阈值阻断（→ 改造 6）。
