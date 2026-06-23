# eval-harness Specification

## Purpose
TBD - created by archiving change phase-0-evals-baseline. Update Purpose after archive.
## Requirements
### Requirement: 评估用例集对齐真实意图口径

评估集 `evals/cases.jsonl` SHALL 以 `输入 → 期望意图` 为用例,且 `expected_intent` MUST 取自真实分类器的 5 类口径之一:`appointment`、`query`、`pay`、`statistics`、`other`。用例集 SHALL 覆盖全部 5 类,并包含边界场景(多槽位、缺槽位追问、改约、与服务无关的输入),总量 SHALL 不少于 18 条。

#### Scenario: 用例意图取值合法

- **WHEN** 加载 `cases.jsonl` 中任一非注释用例
- **THEN** 其 `expected_intent` 必须是 `{appointment, query, pay, statistics, other}` 之一,否则运行器报错并指出行号

#### Scenario: 五类全覆盖

- **WHEN** 统计用例集的 `expected_intent` 分布
- **THEN** 5 个类目每个至少出现一次

#### Scenario: 注释与空行被跳过

- **WHEN** 文件含 `//` 开头的注释行或空行
- **THEN** 运行器加载时跳过它们,不计入用例

### Requirement: 意图分类准确率基线

运行器 `evals/run_evals.py` SHALL 经 `config/model_provider` 实例化真实 `TaskClassifier`,对每条用例执行 `classify_task`,将结果与 `expected_intent` 比对,并 SHALL 输出总准确率、按类目分项准确率,以及逐条错误清单(输入 / 期望 / 实际)。通过的用例 SHALL NOT 逐条打印(成功静默)。

#### Scenario: 产出基线

- **WHEN** 在 API key 可用时运行 `uv run python evals/run_evals.py`
- **THEN** 输出形如"意图准确率 X/N (P%)"的总览,并仅详列判错的用例

#### Scenario: 缺少 API key 时优雅降级

- **WHEN** 运行时检测不到可用模型/API key
- **THEN** 运行器打印清晰提示并以非零退出码结束,不抛出未捕获异常崩溃

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

### Requirement: 评估运行器真跑端到端 AgentLoop 并采集真实工具调用

评估运行器 `evals/run_evals.py` SHALL 在意图分类之外，对每条用例真跑生产路径的 `AgentLoop`（主 Agent → `delegate` → 子 Agent），并从 trace 采集该次运行实际触发的工具调用，填入 `EvalResult.actual_tools`，使工具调用正确率从恒 N/A 翻成真实数字。

运行器 SHALL 自行构造一个带真 `Tracer` 与 `InMemoryExporter` 的主 loop（经 `build_default_registry()` + `build_default_subagent_registry()` + `build_delegate_tool()`），MUST NOT 复用生产路径中默认走 `NoopTracer` 的全局 `AgentLoop` 单例。

工具调用采集 SHALL 以「每条用例一个独立 exporter 沙盒」为边界：收集该 exporter 内所有 span（含子 Agent 各自的 root span）的 `tool_call` 事件，按 `(span.start, 事件顺序)` 还原为有序序列。采集 MUST NOT 仅按单一 `trace_id` 过滤（子 Agent 自开 root 会漏采）。

`EvalResult.actual_tools` SHALL 采全为有序的 `{name, args}` 序列（name 与 args 一并保留）；但本次工具调用正确率指标 SHALL 仍只做工具名集合（`set`）比较，参数级与序列级比对不在本次范围。

真跑路径 SHALL 仅在 API key 可用时启用；无 key 时 MUST 沿用既有优雅降级（提示 + 非零退出，不崩）。

#### Scenario: 真跑后工具调用正确率不再恒 N/A

- **WHEN** 在 API key 可用时运行 `uv run python evals/run_evals.py`，且用例含 `expected_tools`
- **THEN** 运行器真跑 `AgentLoop` 并采集到实际工具调用，工具调用正确率给出真实数字而非 N/A

#### Scenario: 采集覆盖子 Agent 内的工具调用

- **WHEN** 某用例触发主 Agent 经 `delegate` 派生子 Agent，由子 Agent 执行领域工具
- **THEN** 采集到的工具序列包含子 Agent 内实际触发的领域工具（如 `find_technician`），而非仅 `delegate`

#### Scenario: 采全比松

- **WHEN** 采集某次运行的实际工具调用
- **THEN** `actual_tools` 保留每次调用的 `name` 与 `args` 且有序，但工具调用正确率仅按工具名集合比对（不查参数、不校验顺序）

#### Scenario: 无 key 时不真跑

- **WHEN** 运行时检测不到可用模型/API key
- **THEN** 运行器不驱动 `AgentLoop`，沿用既有优雅降级路径（打印用例清单/提示并非零退出）

