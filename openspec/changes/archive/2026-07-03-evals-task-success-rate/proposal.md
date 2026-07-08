## Why

评估分层（§2）里，组件级（意图分类）、端到端轨迹级（工具调用/槽位/多轮）都已真评，**唯独「系统级/业务级」还是纯 ❌**——现有指标全都在问「意图分对没、工具调对没」，没有一个在问「这个任务到底**办成了没**」。一个意图分类 100%、工具 F1 很高的 agent，仍可能从没真正走到「预约建成」这一步。补上一个「任务成功率」指标，能让评估第一次跟业务终态挂钩，也是分层认知里最后一块空白。

## What Changes

- **用例可选标注 `expected_outcome`**：标出该用例期望达成的**业务终态动作**（用「终态工具成功执行」表达，如 appointment→`create_appointment`、query→`search_knowledge`）。只有标注了的用例才计入任务成功率，未标注的（如 pay/statistics/other 当前无工具终态）显式 N/A，不伪造分母（沿用既有范式）。
- **新增「任务成功率」指标**：纯函数、按用例宏平均、缺数据标 N/A，进多指标报告与多采样聚合。判定口径：终态工具被调用**且执行未失败**（复用既有端到端采集，不新触网）。
- **暂不纳入门禁**：v1 只打印/观察，不列入 `GATED_METRICS`——任务成功依赖工具触发，是强非确定项（见记忆 `eval-trigger-nondeterminism`），先观察其 run-to-run 稳定性，避免又添一个误报源。是否纳入留后续切片。
- 文档同步：`evals/README.md` + `docs/agent-eval-fieldguide.md` §2/§5.6/§12（系统级一层从 ❌ → ⚠️ 部分）。

**诚实边界（非目标）**：本项目无真实流量，「任务成功率」是**离线任务完成度的业务信号代理**，不是真实的转化率/满意度/人工介入率——那些需真实用户，属生产级 L3（§14）。本切片不碰真实业务 KPI、不接支付/统计等无工具终态类的成功判定（它们保持 N/A）。

## Capabilities

### New Capabilities
<!-- 无新增能力；沿用既有 eval-harness -->

### Modified Capabilities
- `eval-harness`: 新增「任务成功率（业务终态达成）指标」需求（`expected_outcome` 标注口径、终态工具成功判定、宏平均 + N/A、暂不纳入门禁）。

## Impact

- **数据**：`evals/cases.jsonl`（给有明确业务终态的用例补 `expected_outcome`，主要是 appointment / query）。
- **指标**：`evals/metrics.py`（新增 `task_success_rate` 纯函数 + 进 `build_report`/多采样聚合）；`EvalResult` 可能需带上工具执行成败信号。
- **采集**：`evals/agent_capture.py` / `run_evals.py`（若判定「执行未失败」需从 span 采集工具 observation 的成败，而非只采 name+args）。
- **基线**：`evals/baseline.json` 重定（新增指标，仍只在 dev 上、人审）。
- **文档**：`evals/README.md`、`docs/agent-eval-fieldguide.md`。
- **禁改清单（沿用）**：不改 `services/` / `harness/runtime` / 子 Agent 提示；纯 evals 层 + 数据集标注。
