# eval-harness 规格增量

## ADDED Requirements

### Requirement: 用例并发执行
评估运行器 SHALL 支持以受限并发跑用例：并发度经 `--concurrency N` 配置（默认 5），实现 SHALL 用 `asyncio` 协程 + 信号量限流，MUST NOT 无上限并发。

`--concurrency 1` SHALL 与并发化之前的逐条串行**行为等价**（用作排障与对照的基准路径）。

结果顺序 MUST 与输入用例顺序一致（下游 dev/held-out 拆分依赖同序同长），MUST NOT 按完成先后返回。

失败隔离 SHALL 保持既有语义：单条用例真跑异常记 N/A，MUST NOT 取消或影响其它并发中的用例。

#### Scenario: 并发结果保持输入顺序
- **WHEN** 以 `--concurrency 5` 跑一组用例，且各用例完成先后与输入顺序不同
- **THEN** 返回的结果列表与输入用例列表同序同长

#### Scenario: 并发上限生效
- **WHEN** 以 `--concurrency N` 运行且待跑用例数大于 N
- **THEN** 任一时刻在途用例数不超过 N，其余排队

#### Scenario: 单条失败不影响其它并发用例
- **WHEN** 并发跑中某条用例真跑抛异常
- **THEN** 该条工具/槽位/质量记 N/A，其余用例照常跑完并产出结果

#### Scenario: concurrency=1 等价串行
- **WHEN** 以 `--concurrency 1` 运行
- **THEN** 执行为逐条串行，行为与并发化之前完全一致

### Requirement: 并发不得改变比率型指标
并发执行 SHALL NOT 对比率型指标（工具调用各档、槽位抽取完整率、任务成功率）产生系统性偏移。落地后 SHALL 做一次「`--concurrency 1` vs 并发」的对照跑；若比率型指标偏移超出既有实测 t-CI 半宽，MUST 判为实现缺陷（DB 事务交错、限流致失败增多等）并修复，MUST NOT 直接接受为新常态并据此重定基线。

#### Scenario: 并发与串行的比率型指标一致
- **WHEN** 同一用例集分别以 `--concurrency 1` 与默认并发各跑一次
- **THEN** 比率型指标的差异不超过既有实测半宽；超出则判实现缺陷

## MODIFIED Requirements

### Requirement: 多指标评估报告

评估运行器 `evals/run_evals.py` SHALL 产出多指标报告，至少包含：工具调用正确率、槽位抽取完整率、端到端延迟。端到端延迟 SHALL 以**端到端真跑**（驱动 `AgentLoop` 至最终回复）的每条用例耗时计时并汇总，MUST NOT 以任何单一组件的调用耗时冒充端到端口径。

并发执行时，每条用例的耗时含资源竞争，报告 SHALL 注明该延迟为并发口径、不可与串行跑的历史数字直接比较；实现 MUST NOT 对竞争耗时做任何"扣除/补偿"式的估算修正（无法诚实计算）。延迟不在门禁集内，故该口径变化 SHALL NOT 影响回归判定。

对缺少对应期望字段的用例，相应指标 MUST 显式记为 N/A 并在报告中注明，MUST NOT 静默跳过或伪造分母。报告 SHALL 沿用既有约定：通过用例不逐条打印（成功静默），仅详列判错/异常用例。

#### Scenario: 产出多指标总览

- **WHEN** 在 API key 可用时运行 `uv run python evals/run_evals.py`
- **THEN** 报告输出工具调用正确率、槽位抽取完整率与端到端延迟的总览，并仅详列判错用例

#### Scenario: 延迟为端到端真跑口径

- **WHEN** 报告输出端到端延迟
- **THEN** 其计时覆盖该用例端到端真跑全程（多轮用例为跨轮累计），报告注明口径

#### Scenario: 并发跑的延迟标注竞争口径

- **WHEN** 以并发度大于 1 运行并输出延迟指标
- **THEN** 报告注明该延迟含并发资源竞争、不可与串行历史数字直接比较

#### Scenario: 缺期望字段的指标显式标 N/A

- **WHEN** 部分用例缺少 `expected_slots` 或 `expected_tools`
- **THEN** 报告对这些用例的相应指标标注 N/A 并说明，不把缺失当作通过或失败

#### Scenario: 缺少 API key 时优雅降级

- **WHEN** 运行时检测不到可用模型/API key
- **THEN** 运行器打印清晰提示并以非零退出码结束，不抛出未捕获异常崩溃
