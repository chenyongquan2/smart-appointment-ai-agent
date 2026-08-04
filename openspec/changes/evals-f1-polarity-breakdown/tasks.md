## 1. 分档计算

- [x] 1.1 在 [evals/metrics.py](../../../evals/metrics.py) 加 `tool_call_f1_by_polarity(results) -> list[Metric]`：对 `_tool_eligible` 的同一批用例按 `expected_tools` 空/非空切两组，各自宏平均 F1。**复用与总 F1 完全相同的 per-case 算法**——两边算法一旦分叉，"总 F1 = 两档加权"这个自明关系就不成立了。
- [x] 1.2 每档带 `denominator=n` 与 `extra={"share": n/总数}`（design D3：占比不能省）。
- [x] 1.3 某档为空时标 N/A 并注明"本次可评估集中无该档样本"，**不记 0**（D6）。
- [x] 1.4 `_tool_eligible` 整体为空时两档一并 N/A，沿用总 F1 现有的 note 文案。
- [x] 1.5 接进 `build_report`，紧跟 `tool_call_recall_precision_f1` 之后——顺序即呈现顺序。

## 2. 报告呈现

- [x] 2.1 `_fmt_metric` 对两个分档名特判（与既有「端到端延迟」特判同一手法）：缩进 + 树线 `├`/`└`，打出 `F1、n、占比`。
- [x] 2.2 目视核对单采样报告：三行是**一组**而不是"多了两个指标"（D3 的样例格式）。
- [x] 2.3 确认多采样报告（`format_multisample_report`）下分档同样带出 mean±CI——`aggregate_runs` 按名通吃，预期零改动，但**要跑一遍确认**而不是假定。

## 3. 门禁与基线的隔离（本变更能在冻结期做的前提）

- [x] 3.1 确认 `GATED_METRICS` **不含**分档项，且不改动该常量。
- [x] 3.2 加 `test_polarity_metrics_are_not_gated`：断言 `GATED_METRICS` 与分档名无交集（D2——没有它，日后"既然算出来了不如守上"是很自然的动作）。
- [x] 3.3 加测试断言：引入分档后 `compare_to_baseline` 对同一份 current/baseline 的裁决**逐位不变**（守"总 F1 门禁行为不变"）。
- [x] 3.4 **不跑 `--update-baseline`**、不改 `evals/baseline.json` 一个字节。

## 4. 测试

- [x] 4.1 分档口径：构造正负混合的 `EvalResult` 列表，断言两档 F1 与手算值一致、`n` 与 `share` 正确。
- [x] 4.2 **加权自洽**：断言 `总F1 ≈ 正档F1×正占比 + 负档F1×负占比`（宏平均的定义使其恒成立）。这条是本变更的核心主张，**它红了说明分档算错了**。
- [x] 4.3 判据不依赖 intent：构造一条 intent 为咨询类、但 `expected_tools` 非空的用例，断言它落在正样本档（D1）。
- [x] 4.4 单档为空 → N/A 且非 0（D6）。
- [x] 4.5 `_tool_eligible` 全空 → 两档 N/A。
- [x] 4.6 多采样聚合下分档带 mean±CI（守 2.3）。

## 5. 验证与收尾

- [x] 5.1 `uv run pytest` 全绿——成功静默、只报错。
- [x] 5.2 [docs/agent-eval-fieldguide.md](../../../docs/agent-eval-fieldguide.md) 短板清单「指标对类别构成敏感」一行：把"建议后续按正/负样本分档呈现"改为已做，并指向本 change。
- [x] 5.3 如实记录**没做的**：正样本内部难度分档（design D5）及其触发条件——第 4 期 oncall 数据集建成后，难度口径应由域提供而非写死在 `metrics.py`。
- [x] 5.4 如实记录**离线证明不了的**：本变更未跑真实 LLM 评测（那会消耗数百次调用且冻结期不需要），分档数值在真实运行下的表现未验证；口径正确性由单测的手算对照保证。

## 落地校正（回填）

- **2.3 的"预期零改动"是错的。** `aggregate_runs` 确实按名通吃、分档自动获得 mean±CI，
  但**占比在多采样视图丢了**——`AggregatedMetric` 没有 `extra`。而 `--samples 3` 才是
  推荐跑法，占比只在单采样视图有，等于本变更的主张在主视图上不成立。故给
  `AggregatedMetric` 加了 `share` 字段并在 `aggregate_runs` 里取均值。
  **这正是 tasks 写"要跑一遍确认而不是假定"的原因**——假定的话就漏了。
- **1.1 的算法复用做成了 `_case_rpf`**（返回 recall/precision/F1 三元组），
  总 F1 与分档都调它。原先总 F1 是内联算的，现在抽出来——两边共用一个函数，
  物理上无法分叉。

## 验证记录

- `uv run pytest`：**642 passed / 1 skipped**（本 change 前 633，新增 9 条）。
- **加权自洽实测**：单采样样例 `正 44.4%×38% + 负 80.0%×62% = 66.7%`，与总 F1 逐位一致。
- **基线与用例集零改动**（`git diff master...HEAD -- '*baseline.json' '*cases.jsonl'` 为空）——
  这是本变更能在「预约域评测冻结」期做的前提。
- ⚠ 全量跑第一次时 `test_candidates_are_embedded_concurrently` 红过一次，
  单独跑与在 master 上跑均通过，第二次全量跑也通过——**是并发计时断言在满载下的抖动，
  与本变更无关**（本变更只碰 `evals/metrics.py`）。已另行记下，不在本 change 处理。
