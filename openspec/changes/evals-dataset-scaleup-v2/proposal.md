## Why

评测的**机制层已经建齐**（分档打分、多采样 t-CI、CI 门禁、在线闭环、dev/held-out 留出集、任务成功率）——继续「补机制」边际收益递减。当前最硬的短板是**数据规模**：dev 每类才 ≥5 条、held-out 才 10 条，导致各指标的 95% 置信区间仍然宽、门禁在强非确定项上容易误报、held-out 的防过拟合信号弱。规模化数据集，是让所有已建成机制「跑得稳、测得准」的前置。

## What Changes

- **dev 集扩容**：每个意图类从当前 ≥5 条扩到 **≥30 条**（appointment/query/pay/statistics/other 均达标），覆盖更多措辞变体、边界表述、口语/正式混合、含噪声/多槽位组合。
- **held-out 集扩容**：从 10 条扩到 **≥30 条**（覆盖 5 类），继续物理隔离、不进 baseline、不影响门禁退出码，强化防过拟合信号。
- **多轮用例补充**：在扩容中新增若干 `turns` 多轮用例（预约类的逐步给槽、澄清、改约），让轨迹级评估样本更充分。
- **业务终态标注**：给新增的有明确业务终态的用例（主要 appointment→`create_appointment`、query→`search_knowledge`）补 `expected_outcome`，扩大任务成功率的有效分母。
- **重定基线**：数据集变更后按既有范式 `--samples 3` 在 **dev** 上重定 `evals/baseline.json`（held-out 不进基线）；门禁指标 `{意图, 工具F1, 槽位}` 以扩容后 dev 集为准。
- **文档同步**：`evals/README.md` 记录新的规模/每类下限；`docs/agent-eval-fieldguide.md` §12 速查表 + §13 路线图更新数据规模现状。

**诚实边界（非目标）**：本切片只做**离线数据集规模化 + 标注**，不引入新指标、不改评分口径、不碰真实流量。规模化到「几百条」是长期方向，本切片先把每类下限从 5 抬到 30（held-out 到 30）作为可交付的第一台阶，不追求一步到位。**禁改**：`services/`、`harness/runtime`、子 Agent 提示——纯 evals 层 + 数据集标注。

## Capabilities

### New Capabilities
<!-- 无新增能力；沿用既有 eval-harness -->

### Modified Capabilities
- `eval-harness`: 新增/收紧「数据集规模与覆盖」需求——dev 每类 ≥30 条、held-out ≥30 条覆盖 5 类、扩容用例遵循既有 schema（含多轮 `turns` 与 `expected_outcome` 标注口径）、数据集变更连带在 dev 上重定 baseline。

## Impact

- **数据**：`evals/cases.jsonl`（新增大量单轮/多轮用例 + `expected_outcome` 标注；这是本切片的主体工作量）。
- **基线**：`evals/baseline.json` 重定（`--samples 3`，仅 dev，人审）——数据集变更属于会改门禁判定的行为变更（见记忆 `eval-trigger-nondeterminism`），必须连带重定。
- **文档**：`evals/README.md`、`docs/agent-eval-fieldguide.md`。
- **不改**：`evals/` 下的运行器/指标/采集代码（`run_evals.py`/`metrics.py`/`agent_capture.py` 等）——机制已足够，本切片只喂数据；如扩容中发现某 split/schema 处理有缺陷再最小修补。
- **禁改清单（沿用）**：`services/` / `harness/runtime` / 子 Agent 提示。
