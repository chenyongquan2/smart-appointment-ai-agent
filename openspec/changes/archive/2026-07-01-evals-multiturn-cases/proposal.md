## Why

教材 [§2](../../../docs/agent-eval-fieldguide.md) 的分层认知图里，「端到端·轨迹/多轮」这一层一直是 ❌——`evals/cases.jsonl` 全为单轮输入，运行器 `_run_once` / `run_and_capture` 也只吃单条 `input: str`。改造 1 已把 AgentLoop 接进评估、`actual_tools`/`actual_slots` 出真数，但**只评得到「单轮一句话能不能触发对的工具」**，评不到 agent 真正的难点：跨轮维持状态、在追问后补全槽位、把多轮信息汇总成一次正确的工具链。这是改造 8 续做里 ROI 最高、最能抬升项目定性（从「单轮 agent 评估」→「多轮轨迹评估」）的一片。

## What Changes

- **扩展用例形态支持多轮**：`cases.jsonl` 新增可选 `turns`（有序用户话语列表），与既有单轮 `input` 并存且向后兼容（`input` 等价于单元素 `turns`）。多轮用例的 `expected_tools` / `expected_slots` 口径为**整段对话累计**（跨所有轮次合并），与既有单轮口径自然一致。
- **运行器按轮驱动 AgentLoop**：新增多轮采集路径——对一条多轮用例，复用同一带 `Tracer`/`InMemoryExporter` 沙盒的主 loop，逐轮调用 `loop.run(turn, history=accumulated_history)`，把每轮用户话与 agent 回复累积进 `history`（与生产 `chat_handler` 的「最近 N 轮窗口」一致），跑完从沙盒**跨所有轮次**还原有序工具序列与槽位，最终回复取末轮回复喂 judge。
- **明确多轮的意图口径**：多轮用例的意图分类对**首轮**（确立意图的开场白）跑 `classify_task`，避免重构单轮分类器；`expected_intent` 仍取 5 类之一。
- **补多轮用例**：新增若干条「追问补全」「改约」「先咨询后预约」式多轮预约用例（标 `expected_tools`/`expected_slots`），覆盖单轮覆盖不到的轨迹场景。
- **不改业务逻辑**：不动 `services/`、`harness/runtime`、子 Agent 编排与系统提示（CLAUDE.md 禁改清单）；变更集中在 `evals/`（用例 + 运行器/采集层）与文档。
- **重定基线（人审）**：新增多轮用例改变了评估集，经人审批准在新集上 `--update-baseline --samples 3` 重定 `baseline.json`，使门禁 like-to-like；非自动、不绕过门禁。

## Capabilities

### New Capabilities

（无——复用既有 `eval-harness` 能力，扩展其用例形态与运行器口径。）

### Modified Capabilities

- `eval-harness`: 扩展「评估用例集」需求允许多轮 `turns` 形态；新增「多轮对话用例的端到端轨迹评估」需求，约束运行器按轮驱动 AgentLoop 累积 history 并跨轮采集工具/槽位、多轮意图对首轮判定的口径，以及多轮 `expected_tools`/`expected_slots` 的「整段累计」语义。既有单轮行为与所有现有需求口径保持不变（向后兼容）。

## Impact

- **数据**：`evals/cases.jsonl`（新增多轮 `turns` 用例，标 `expected_tools`/`expected_slots`）。
- **代码（仅 `evals/`）**：`evals/run_evals.py`（用例加载允许 `turns`、单/多轮分派）、`evals/agent_capture.py`（新增多轮采集函数，复用既有沙盒/采集逻辑）；`metrics.py` 指标算法与口径**不变**。
- **测试**：新增多轮采集/分派的离线确定性单测（脚本化 fake LLM，沿用改造 1 的测试范式）。
- **文档**：`docs/agent-eval-fieldguide.md`（§2 速查表「轨迹/多轮」转 ✅/部分、§13 改造 8 续做状态收口）、`evals/README.md`。
- **`baseline.json`**：经人审在新集上重定（刷新各指标稳定均值）。
- **不影响**：`services/`、`harness/`、`agents/` 业务逻辑与子 Agent 提示。
- **验证**：`uv run pytest` 绿；`uv run python evals/run_evals.py --gate --samples 3` 多轮用例真跑、门禁稳定守 3 项。
