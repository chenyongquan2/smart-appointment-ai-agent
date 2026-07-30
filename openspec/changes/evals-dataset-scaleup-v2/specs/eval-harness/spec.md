## ADDED Requirements

### Requirement: 数据集规模与每类覆盖下限

评估用例集 SHALL 满足**最小规模与每类覆盖下限**，使已建成的评估机制（多采样 t-CI、门禁、held-out 防过拟合）获得统计上足够的样本支撑，而非在稀疏数据上产生宽置信区间与门禁误报。

- **dev 每类下限**：dev 子集中，5 类意图（`appointment` / `query` / `pay` / `statistics` / `other`）**每一类** SHALL 至少有 **30 条**用例。
- **held-out 规模与覆盖**：held-out 子集 SHALL 至少有 **30 条**用例，且 SHALL 覆盖全部 5 类意图（每类 ≥1 条）。
- **多样性**：扩容用例 SHALL 覆盖措辞变体（口语/正式、简/繁、同义改写）、边界与含噪声表述、多槽位组合，MUST NOT 靠机械复制同一句式凑数（同一用例的近似重复不计入下限）。
- **schema 合规**：所有扩容用例 SHALL 遵循既有用例 schema——单轮用 `input`、多轮用 `turns`（二者互斥）；有明确业务终态的用例（主要 `appointment`→`create_appointment`、`query`→`search_knowledge`）SHALL 标注 `expected_outcome`；集归属沿用既有 `split` 口径（缺省 dev）。
- **门禁基线连带重定**：数据集规模变更后 SHALL 在 **dev** 子集上按既有范式（`--samples 3`、人审）重定 `evals/baseline.json`；held-out MUST NOT 进入基线。

#### Scenario: dev 每类满足 30 条下限

- **WHEN** 统计 dev 子集内各意图类的用例数
- **THEN** 5 类每一类的计数均 ≥30

#### Scenario: held-out 满足规模与 5 类覆盖

- **WHEN** 统计 held-out 子集
- **THEN** 总数 ≥30 且 5 类意图每类至少出现 1 条

#### Scenario: 扩容用例遵循既有 schema 与标注口径

- **WHEN** 加载任一扩容用例
- **THEN** 它符合单轮/多轮互斥的字段约束、集归属校验通过；若属有业务终态类则带合法 `expected_outcome`，运行器 MUST NOT 因格式非法报错

#### Scenario: 数据集变更后门禁基线在 dev 上重定

- **WHEN** 完成本次扩容
- **THEN** `evals/baseline.json` 以扩容后 dev 子集、`--samples 3` 重定，门禁指标 `{意图, 工具F1, 槽位}` 以新 dev 集为准，held-out 不影响基线内容与退出码
