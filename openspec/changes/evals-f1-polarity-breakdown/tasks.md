## 1. 分档计算

- [ ] 1.1 在 [evals/metrics.py](../../../evals/metrics.py) 加 `tool_call_f1_by_polarity(results) -> list[Metric]`：对 `_tool_eligible` 的同一批用例按 `expected_tools` 空/非空切两组，各自宏平均 F1。**复用与总 F1 完全相同的 per-case 算法**——两边算法一旦分叉，"总 F1 = 两档加权"这个自明关系就不成立了。
- [ ] 1.2 每档带 `denominator=n` 与 `extra={"share": n/总数}`（design D3：占比不能省）。
- [ ] 1.3 某档为空时标 N/A 并注明"本次可评估集中无该档样本"，**不记 0**（D6）。
- [ ] 1.4 `_tool_eligible` 整体为空时两档一并 N/A，沿用总 F1 现有的 note 文案。
- [ ] 1.5 接进 `build_report`，紧跟 `tool_call_recall_precision_f1` 之后——顺序即呈现顺序。

## 2. 报告呈现

- [ ] 2.1 `_fmt_metric` 对两个分档名特判（与既有「端到端延迟」特判同一手法）：缩进 + 树线 `├`/`└`，打出 `F1、n、占比`。
- [ ] 2.2 目视核对单采样报告：三行是**一组**而不是"多了两个指标"（D3 的样例格式）。
- [ ] 2.3 确认多采样报告（`format_multisample_report`）下分档同样带出 mean±CI——`aggregate_runs` 按名通吃，预期零改动，但**要跑一遍确认**而不是假定。

## 3. 门禁与基线的隔离（本变更能在冻结期做的前提）

- [ ] 3.1 确认 `GATED_METRICS` **不含**分档项，且不改动该常量。
- [ ] 3.2 加 `test_polarity_metrics_are_not_gated`：断言 `GATED_METRICS` 与分档名无交集（D2——没有它，日后"既然算出来了不如守上"是很自然的动作）。
- [ ] 3.3 加测试断言：引入分档后 `compare_to_baseline` 对同一份 current/baseline 的裁决**逐位不变**（守"总 F1 门禁行为不变"）。
- [ ] 3.4 **不跑 `--update-baseline`**、不改 `evals/baseline.json` 一个字节。

## 4. 测试

- [ ] 4.1 分档口径：构造正负混合的 `EvalResult` 列表，断言两档 F1 与手算值一致、`n` 与 `share` 正确。
- [ ] 4.2 **加权自洽**：断言 `总F1 ≈ 正档F1×正占比 + 负档F1×负占比`（宏平均的定义使其恒成立）。这条是本变更的核心主张，**它红了说明分档算错了**。
- [ ] 4.3 判据不依赖 intent：构造一条 intent 为咨询类、但 `expected_tools` 非空的用例，断言它落在正样本档（D1）。
- [ ] 4.4 单档为空 → N/A 且非 0（D6）。
- [ ] 4.5 `_tool_eligible` 全空 → 两档 N/A。
- [ ] 4.6 多采样聚合下分档带 mean±CI（守 2.3）。

## 5. 验证与收尾

- [ ] 5.1 `uv run pytest` 全绿——成功静默、只报错。
- [ ] 5.2 [docs/agent-eval-fieldguide.md](../../../docs/agent-eval-fieldguide.md) 短板清单「指标对类别构成敏感」一行：把"建议后续按正/负样本分档呈现"改为已做，并指向本 change。
- [ ] 5.3 如实记录**没做的**：正样本内部难度分档（design D5）及其触发条件——第 4 期 oncall 数据集建成后，难度口径应由域提供而非写死在 `metrics.py`。
- [ ] 5.4 如实记录**离线证明不了的**：本变更未跑真实 LLM 评测（那会消耗数百次调用且冻结期不需要），分档数值在真实运行下的表现未验证；口径正确性由单测的手算对照保证。
