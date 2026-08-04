## Why

`工具调用-F1` 是**宏平均**，而 [evals/metrics.py:148](../../../evals/metrics.py) 对空期望集给**免费满分**：

```python
recall = hit / len(expected) if expected else 1.0      # 期望为空 → 召回记 1
precision = hit / len(actual) if actual else 1.0        # 实际为空 → 精确记 1
```

`pay` / `statistics` / `other` 三类的 `expected_tools` 都是 `[]`，agent 只要不乱调工具就白得 F1=1.0。当前 dev 集里这类占 **15/41 (37%)**。

已放弃的 `evals-dataset-scaleup-v2` 在真实数据上把这件事量化了（结论已摘回 [归档 design](../archive/2026-08-03-evals-dataset-scaleup-v2-abandoned/design.md)）：把负样本占比推到 90/154 (58%) 后，F1 从 56.2% **机械升到 78.5%**，而同期「3 工具难例」占比从 65% 掉到 38%——**没有任何证据表明模型能力变化**。拆开看：

| | n | F1 |
|---|---|---|
| 负样本 | 90 | 95.6% |
| 正样本 | 64 | 54.5% |
| 整体 | 154 | **78.5%** |

由此得到的结论是：**单一宏平均 `工具调用-F1` 不是能力指标，而是一个「按混合比例加权的平均数」**。用作门禁（同一数据集两侧比较）没问题；被读作"能力 78.5%"就是错的。

更麻烦的不是跨版本不可比（那个已知，故要重定基线），而是**同一个数字内部，难例失败与易例满分被混在一起看不见**——78.5% 里有一大半来自"不该调工具时没乱调"这种低难度贡献。

**为什么现在做**：第 4 期要用 oncall 真实排障对话建新数据集，走「多样性优先」路线必然引入大量只期望 0–1 个工具的简单请求（问状态、闲聊、无关提问），指标会自己涨。**在建数据集之前把分档做好，否则新数据集会被同一个陷阱骗一次**——而那次没有旧基线可对照，会更难发现。

## What Changes

- **新增两个分档指标**：`工具调用-F1(正样本)`（`expected_tools` 非空）与 `工具调用-F1(负样本)`（`expected_tools` 为空），与总 F1 同为宏平均、同一批可评估用例。
- **报告呈现带占比**：两档各自打出 `n` 与**占可评估集的比例**。占比是重点——没有它就看不出构成漂移，而"构成加权平均"正是要暴露的东西。
- **两档 MUST NOT 进 `GATED_METRICS`**：进了就需要重定基线，而重定基线是「预约域评测冻结」明令禁止的。加一条测试钉死这一点。
- **总 F1 的口径、数值、门禁行为一律不变**——本变更只增加可见度，不改任何判定。

非破坏性：`compare_to_baseline` 只遍历 `GATED_METRICS`，新指标它压根不看；`baseline.json` 不动，`--gate` 行为逐位不变。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `eval-harness`：`多指标评估报告` 这条 Requirement 扩展——工具调用 F1 SHALL 按正/负样本分档呈现并带构成占比；分档 MUST NOT 进门禁集。

## Impact

- **代码**：[evals/metrics.py](../../../evals/metrics.py)（新增分档计算 + 报告渲染）。
- **测试**：[tests/](../../../tests/) 新增分档口径与"不入门禁"的守护测试。
- **文档**：[docs/agent-eval-fieldguide.md](../../../docs/agent-eval-fieldguide.md) 短板清单里「指标对类别构成敏感」一行从"建议后续做"改为已做。
- **不影响**：`baseline.json`（不重定）、`--gate` 退出码、`cases.jsonl`（不动一个字）、Agent 运行时。
- **⚠ 明确不做**：正样本**内部**按难度（期望工具数 1 vs 3）再分一档——见 design D5。
