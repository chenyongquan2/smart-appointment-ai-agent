## ADDED Requirements

### Requirement: 多次采样与聚合指标置信区间

评估运行器 SHALL 支持可配的多次采样：经 `--samples N`（默认 `N=1`）控制整套用例的重跑次数。`N=1` 时行为 SHALL 与单次跑完全一致（向后兼容）。`N>1` 时运行器 SHALL 整套用例独立重跑 N 次，并对每个聚合指标跨 N 次跑计算 `mean` 与置信区间。

置信区间 SHALL 用 **t 分布**计算：`mean ± t_(N-1, 0.975) · s/√N`（s 为 N 个 run 级聚合值的样本标准差），把每次整套跑的聚合值当作一个观测。实现 MUST NOT 对小样本用正态(z)近似代替 t。t 临界值 MAY 用硬编码小表（零额外依赖）。

该 CI MUST 在报告中被标注为 **run-to-run（LLM 抖动）** 的不确定性，并 MUST NOT 被声称为涵盖数据集大小的不确定性（后者需更大用例集，不在本能力范围）。

当 N 次跑的聚合值完全相同（`s=0`，如 `temperature=0` 残余抖动可忽略）时，CI 宽度 SHALL 为 0，报告 SHALL 给出点值并标注稳定，MUST NOT 当作错误。

CI 与方差的计算 SHALL 为纯函数（吃一组 per-run 指标值、不触网、可离线确定性单测），与触网的采样循环解耦。

#### Scenario: 默认单次跑向后兼容

- **WHEN** 不传 `--samples`（或 `--samples 1`）运行评估
- **THEN** 行为与既有单次跑完全一致，报告不含 CI 列

#### Scenario: 多次采样产出 mean ± CI

- **WHEN** 以 `--samples 5` 运行，且某聚合指标在 5 次跑中取值不全相同
- **THEN** 报告对该指标给出 `mean ± CI（n=5 次）`，CI 由 t 分布按 `mean ± t_(4,0.975)·s/√5` 算出

#### Scenario: 零方差给零宽 CI

- **WHEN** 某指标在 N 次跑中取值完全相同
- **THEN** 报告给出该指标的点值、CI 宽度为 0 并标注稳定，不报错

#### Scenario: CI 含义被正确标注

- **WHEN** 报告展示置信区间
- **THEN** 标注其为 run-to-run（LLM 抖动）不确定性，且不声称涵盖数据集大小的不确定性
