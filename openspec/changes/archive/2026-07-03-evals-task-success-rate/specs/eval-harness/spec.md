## ADDED Requirements

### Requirement: 任务成功率（业务终态达成）指标

评估 SHALL 提供一个**任务成功率**指标，度量 agent 是否真正达成了用例意图对应的**业务终态动作**，补齐系统级/业务级评估——区别于「意图分对没、工具调对没」，它问「任务办成了没」。

**标注口径**：用例可选携带 `expected_outcome` 字段，值为代表业务终态的**终态工具名**（如 `create_appointment`、`search_knowledge`）。仅当用例标注了 `expected_outcome` **且**本次端到端真跑捕获到了工具序列（`actual_tools` 非 None）时，该用例才计入任务成功率；未标注或未捕获的用例 SHALL 显式 N/A（不伪造分母，沿用既有范式）。无工具终态的意图（当前的 `pay`/`statistics`/`other`）SHALL 不标注 `expected_outcome`，即恒不计入。

**成功判定**：一条用例「任务成功」当且仅当——其 `expected_outcome` 指定的终态工具在捕获到的工具调用序列中出现，**且该工具的执行结果不是失败**（失败口径复用 `harness/observability/trace_signals.py` 的 `TOOL_FAILURE_PREFIX`——工具异常被 `AgentLoop._dispatch` 吞成以「工具执行失败」开头的 observation）。终态工具被调用但其 observation 是失败，SHALL 计为不成功。

**聚合**：任务成功率 = 成功用例数 / 计入用例数，按用例**等权**（与既有指标一致）。该指标 SHALL 进多指标报告与多采样聚合（mean ± t-CI），纯函数计算、可离线确定性单测。

**门禁**：本指标 v1 SHALL NOT 纳入 `GATED_METRICS`——任务成功依赖工具触发，是强非确定项，先只打印/观察其 run-to-run 稳定性，是否纳入门禁留后续切片决定。

**诚实边界**：本指标是**离线任务完成度的业务信号代理**，MUST NOT 被表述为真实转化率/满意度/人工介入率（那些需真实用户流量，属生产级）。报告中 SHALL 保持这一口径清晰。

#### Scenario: 标注了 expected_outcome 且终态工具成功 → 计成功

- **WHEN** 一条用例标注 `expected_outcome: "create_appointment"`，本次真跑捕获到 `create_appointment` 被调用且其 observation 非失败
- **THEN** 该用例计入任务成功率且判为成功

#### Scenario: 终态工具被调用但执行失败 → 计不成功

- **WHEN** 用例标注 `expected_outcome: "create_appointment"`，`create_appointment` 出现在工具序列中，但其 observation 以「工具执行失败」开头
- **THEN** 该用例计入任务成功率但判为不成功

#### Scenario: 终态工具未被调用 → 计不成功

- **WHEN** 用例标注 `expected_outcome`，但该终态工具未出现在捕获的工具序列中
- **THEN** 该用例计入任务成功率且判为不成功

#### Scenario: 未标注 expected_outcome → 显式 N/A 不计入

- **WHEN** 一条用例未标注 `expected_outcome`（如 pay/statistics/other），或本次未捕获到 `actual_tools`
- **THEN** 该用例不计入任务成功率；当全部用例都不计入时，指标整体显式标 N/A（附原因），MUST NOT 伪造分母

#### Scenario: 任务成功率不触发门禁

- **WHEN** 运行 `--gate`
- **THEN** 任务成功率照常打印，但 MUST NOT 参与回归判定、MUST NOT 触发非零退出（不在 `GATED_METRICS` 内）
