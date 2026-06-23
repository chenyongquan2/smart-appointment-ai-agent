## ADDED Requirements

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
