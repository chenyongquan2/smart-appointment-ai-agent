## MODIFIED Requirements

### Requirement: 工具调用为前瞻注解

用例 MAY 携带 `expected_tools` 字段。自本能力起，评估运行器 SHALL 在用例提供 `expected_tools` 时计算工具调用正确率（实际触发的工具序列/集合与期望的比对），并将其纳入多指标报告；当用例不含 `expected_tools` 时，该指标对该用例记为 N/A 而非计入对错。意图准确率的判定 SHALL NOT 受 `expected_tools` 影响。

#### Scenario: expected_tools 不影响意图准确率

- **WHEN** 计算意图分类准确率
- **THEN** `expected_tools` 字段被忽略，不参与意图对错判定

#### Scenario: 提供 expected_tools 时计入工具调用正确率

- **WHEN** 某用例含 `expected_tools` 且评估实际执行了工具
- **THEN** 运行器比对实际与期望工具，计入工具调用正确率指标

#### Scenario: 缺 expected_tools 时记 N/A

- **WHEN** 某用例不含 `expected_tools`
- **THEN** 该用例的工具调用正确率记为 N/A，不伪造分母、不计入对错

## ADDED Requirements

### Requirement: 多指标评估报告

评估运行器 `evals/run_evals.py` SHALL 在意图准确率之外，产出多指标报告，至少包含：工具调用正确率、槽位抽取完整率、端到端延迟（每条用例计时并汇总）。对缺少对应期望字段的用例，相应指标 MUST 显式记为 N/A 并在报告中注明，MUST NOT 静默跳过或伪造分母。报告 SHALL 沿用既有约定：通过用例不逐条打印（成功静默），仅详列判错/异常用例。

#### Scenario: 产出多指标总览

- **WHEN** 在 API key 可用时运行 `uv run python evals/run_evals.py`
- **THEN** 报告输出意图准确率、工具调用正确率、槽位抽取完整率与端到端延迟的总览，并仅详列判错用例

#### Scenario: 缺期望字段的指标显式标 N/A

- **WHEN** 部分用例缺少 `expected_slots` 或 `expected_tools`
- **THEN** 报告对这些用例的相应指标标注 N/A 并说明，不把缺失当作通过或失败

#### Scenario: 缺少 API key 时优雅降级

- **WHEN** 运行时检测不到可用模型/API key
- **THEN** 运行器打印清晰提示并以非零退出码结束，不抛出未捕获异常崩溃
