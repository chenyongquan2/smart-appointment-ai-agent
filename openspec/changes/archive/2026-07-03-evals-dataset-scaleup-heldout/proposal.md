## Why

当前评估集只有 35 条、全为手写合成、且**无 dev / held-out 切分**。两个直接后果:① 任何指标的统计意义都薄弱(35 条的 85% 与 300 条的 85% 可信度天差地别);② 没有留出集,调 prompt / 策展用例时会**在同一批数据上过拟合**——教材 §4.2 明确把「held-out 缺失」列为本项目当前最大数据风险。这是评测成熟度从「机制齐全」走向「结论可信」必须先解决的地基,且不依赖任何外部条件(RAG 服务迁移、真实流量),ROI 最高。

## What Changes

- **引入 held-out 留出集机制**:给用例增加一个可标记的「集归属」维度(dev / held-out),运行器据此区分——默认跑 dev 集(用于日常调试、prompt 调优、门禁),held-out 集**仅在显式请求时评估、且绝不用于任何调优**。门禁基线与回归判定继续基于 dev 集;held-out 作为独立的「过拟合体检」按需跑、单独记录。
- **规模化首切片(立机制 + 有意义扩充)**:不追求一次生成几百条,而是把切分机制立起来,并把用例扩充到一个对每类意图都有统计意义的量级(在保持 5 类意图覆盖、单轮/多轮两种形态的前提下扩充),并从中切出 held-out 子集。
- **重定 baseline(人审)**:用例集一变,旧基线与新集 apples-to-oranges,按既有约定在新 dev 集上 `--update-baseline --samples 3` 重定,走人审、不自动。
- 文档同步:`evals/README.md` 增补 dev/held-out 口径与运行方式;`docs/agent-eval-fieldguide.md` §4.2 / §12 / §13 改造 8 更新现状。

非目标(本切片明确不做):从真实流量采样(依赖改造 7 有真流量)、几百条的完整规模化(本切片只立机制 + 首增量,规模化仍是"持续投入")、任何自动生成用例的流水线。

## Capabilities

### New Capabilities
<!-- 无新增能力;沿用既有 eval-harness -->

### Modified Capabilities
- `eval-harness`: 新增「用例集 dev / held-out 切分」需求(集归属标记、运行器区分、held-out 不参与调优与门禁、held-out 按需独立评估);既有「评估用例集对齐真实意图口径」需求扩充规模与切分覆盖度约束。

## Impact

- **数据**:`evals/cases.jsonl`(新增集归属标记 + 扩充用例);可能新增独立 held-out 文件或用字段标记(方案在 design 定)。
- **运行器**:`evals/run_evals.py`(加载时识别集归属、`--include-heldout` 类开关、报告分集呈现);门禁口径不变(仍守 dev 集正确性子集)。
- **基线**:`evals/baseline.json` 在新 dev 集上重定(人审)。
- **文档**:`evals/README.md`、`docs/agent-eval-fieldguide.md`。
- **禁改清单(沿用改造 8)**:不改 `services/` / `harness/runtime` / 子 Agent 提示;纯数据集 + evals 层变更。
