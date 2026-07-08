## Context

评估分层里系统级/业务级是唯一纯 ❌ 的一层。现有采集（`evals/agent_capture.py` → `collect_tool_calls`）只从 span 的 `tool_call` 事件还原 `[{name, args}]`，**不含工具执行结果**。判定「任务办成了没」需要知道终态工具是否被调用、且是否执行成功。

已有可复用件：
- span 的 `observation` 事件 payload 形如 `{"result": ...}`；工具失败被 `AgentLoop._dispatch` 吞成以「工具执行失败」开头的 result（`trace_signals.TOOL_FAILURE_PREFIX`）。
- `metrics.py` 的 N/A 范式、宏平均、`AggregatedMetric` 多采样聚合、`build_report` 装配。

约束（禁改清单）：纯 `evals/` 层 + 数据集标注，不改 `services/`/`harness/runtime`/子 Agent 提示。可**读** `harness/observability`（分层允许 evals 依赖 harness）。

## Goals / Non-Goals

**Goals:**
- 新增 `task_success_rate` 指标：用例标 `expected_outcome`（终态工具名），成功 = 该工具被调用且 observation 非失败；宏平均、N/A 范式、进报告 + 多采样聚合。
- 采集层能拿到「终态工具是否成功执行」——在 evals 层从 span 配对 `tool_call`→`observation`，不改 harness。
- v1 只打印、不纳入门禁。

**Non-Goals:**
- 真实业务 KPI（转化率/满意度/人工介入率）——需真实流量，属 L3。
- 给 pay/statistics/other 造工具终态（它们无工具终态，保持不标注 = N/A）。
- 纳入门禁（留后续切片，先观察稳定性）。

## Decisions

### D1. 成功信号：新增 evals 层 `collect_tool_outcomes(spans)`，span 内配对 tool_call→observation
新增纯函数（放 `evals/trace_collect.py`，与 `collect_tool_calls` 同层）：遍历每个 span，按事件顺序把每个 `tool_call` 事件与其后**同 span 内下一个 `observation` 事件**配对，产出 `[{name, ok}]`（`ok = not result.startswith(TOOL_FAILURE_PREFIX)`）。
- **为什么按 span 内顺序配对**：`AgentLoop` 一个 step span 内是「tool_call → observation」紧邻的事件流，同 span 内顺序配对确定、可离线单测；跨 span 不配对（避免误配子 Agent 边界）。
- **备选**：改 `harness` 让 tool_call 事件直接带成败——违反禁改清单，否决。
- **delegate 编排工具**：`collect_tool_calls` 默认剔除 delegate；`collect_tool_outcomes` 同样剔除（终态只可能是领域工具）。

### D2. `EvalResult` 增 `actual_tool_outcomes: Optional[list[dict]]`
`run_and_capture(_multiturn)` 的 `CaptureResult` 增一字段 `tool_outcomes`（跨轮，与 `tool_calls` 同源同序），`_run_once` 填进 `EvalResult.actual_tool_outcomes`。None = 未真跑/失败（该用例指标 N/A）。既有字段与行为不变（向后兼容）。

### D3. 指标 `task_success_rate(results)`（metrics.py，纯函数）
- eligible = `r.expected_outcome` 非空 **且** `r.actual_tool_outcomes is not None` 的用例。
- 单条成功 = 存在 outcome，其 `name == expected_outcome` 且 `ok is True`（同名多次取「任一成功即成功」，宽松但贴合「办成了」语义）。
- 值 = 成功数 / eligible 数；eligible 为空 → `Metric(na=True, note=...)`。
- 进 `build_report` 的 metrics 列表（放槽位之后、延迟之前）；`aggregate_runs` 靠指标名自动纳入（无需改聚合逻辑）。

### D4. 不纳入门禁
不加进 `GATED_METRICS`。`compare_to_baseline` 只遍历 `GATED_METRICS`，故 task_success_rate 自动只出现在报告、不触发退出码——无需额外改门禁代码。基线快照仍会收录它（`report_to_baseline` 收全部非 N/A 指标），仅作历史参照。

### D5. 标注哪些用例
只给有工具终态的意图标 `expected_outcome`：
- `appointment`（信息齐全、期望建单的）→ `create_appointment`；
- `query` → `search_knowledge`。
追问补全/改约类多轮同理标 `create_appointment`。pay/statistics/other 不标。dev/held-out 都可标（held-out 仍只在 `--include-heldout` 时算、不进门禁基线，切分口径不变）。

## Risks / Trade-offs

- **[强非确定拉低/抖动 task_success]** → 预约触发本就 1/3~3/3 波动（记忆 `eval-trigger-nondeterminism`），叠加「还要执行成功」会更低更抖。缓解：v1 不纳门禁、只观察；报告如实呈现；靠数据集冗余 + `--samples` 看均值。
- **[span 内配对错位]** → 若某 step 有多个 tool_call 与 observation 交错，顺序配对可能错位。缓解：实测 `AgentLoop` 每 step 单工具调用；单测覆盖「一 step 一对」的正常形态，多工具交错标为已知简化。
- **[create_appointment 在 eval 环境常执行失败]** → 若真如此，task_success 会很低——但这**正是有价值的诚实信号**（agent 驱动到了终态但没真办成），不粉饰。报告注明口径。
- **[值口径被误读为真实业务成功率]** → 报告/文档明确标「离线完成度代理，非真实 KPI」。

## Migration Plan

1. `collect_tool_outcomes` + 单测（离线，脚本化 span：成功/失败/未调用/多工具）。
2. `CaptureResult.tool_outcomes` + `EvalResult.actual_tool_outcomes` 贯通采集链（`agent_capture`/`run_evals._run_once`）+ 单测。
3. `task_success_rate` 指标 + 进 `build_report` + 单测（成功/失败/未调用/N/A）。
4. `cases.jsonl` 给 appointment/query 用例标 `expected_outcome`。
5. `uv run pytest` 绿 → 人审 → 新 dev 集重定基线（含新指标）→ `--gate` 复核仍守 3 项（新指标不影响门禁）。
6. 文档同步 → 归档。

回滚：纯增量，revert 代码 + 数据 + 恢复旧 baseline。

## Open Questions

- 「执行成功」是否要求终态工具在**最后**出现（真正终态）vs 只要出现过——v1 取「出现过且成功」（宽松），后续可收紧为序列末位。
- 多采样下 task_success 的 CI 会很宽，是否值得纳入门禁——待观察数据后定。
