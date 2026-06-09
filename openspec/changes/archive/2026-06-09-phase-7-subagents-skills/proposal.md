## Why

harness 已具备 loop（Phase 3）、记忆（Phase 4）、护栏（Phase 5）、可观测（Phase 6），但**主 Agent 仍是「单一 loop + 一个扁平 5 工具集」**：所有工具混在一个 `ToolRegistry` 里、塞进同一个 system prompt 与同一段上下文。随着能力增多，这会带来三个问题——工具/提示膨胀稀释模型注意力、不同领域（预约 / 咨询 / 行为分析）的上下文互相污染、复杂任务无法各自独立推理。Phase 7 是路线图最后一个里程碑，要把「预约 / 咨询 / 行为分析」沉淀为**专用子 Agent**，由主 Agent 通过一个 `delegate` 工具**自主决定派生哪个子 Agent**（对齐 Claude Code sub-agents / OpenClaw Skills），让每个子 Agent 在独立上下文、独立工具子集里跑自己的 mini TAO 循环，结果汇总回主 Agent——而非由开发者硬编码路由。

## What Changes

- **子 Agent 抽象（新）**：新建 `harness/subagents/`，定义 `SubAgent`——声明 `name / description / 工具子集 / system prompt`，内部复用既有 `AgentLoop` 在**独立上下文**跑一次 mini TAO 循环并返回最终文本。子 Agent 复用现有 `Tool` / `ToolRegistry` / tracer / guardrails，不重写业务逻辑（黄金准则：工具是薄封装）。
- **三个专用子 Agent（新）**：`appointment`（持有 find_technician / check_availability / create_appointment / get_user_preferences）、`consultant`（持有 search_knowledge）、`user_behavior`（持有 get_user_preferences）。各自独立的 system prompt 与工具子集，取代旧 `agents/` 下的硬编码路由。
- **delegate 工具（新）**：薄封装的 `delegate(subagent, task)` 工具，让**主 Agent**（顶层 `AgentLoop`）自主决定把任务交给哪个子 Agent；分发到对应 `SubAgent` 跑独立 loop，结果回灌主 Agent 上下文。主 registry 注册 `delegate`，主 system prompt 列出可派生的子 Agent 及其职责（结构化、显式优于隐式）。
- **Skills 化（新，按需加载）**：定义 `Skill`（带 `name / description / 何时加载`）与 `SkillRegistry`——把可复用能力（如 RAG 检索、偏好解读）声明为 skill，按描述匹配**按需加载**进子 Agent 上下文，而非全量常驻，对齐 Claude Code skills 机制。
- **接线（改）**：`api/chat_handler.py` 的主 registry 接入 `delegate`，主 loop 改为「决策 + 派生」而非直接执行领域工具；保持 session 隔离、记忆注入、`[THOUGHT]/[REPLY]` 前缀语义不变（前端无需改）。

## Capabilities

### New Capabilities
- `subagent-delegation`: 子 Agent 抽象（独立上下文 + 工具子集 + system prompt，复用 `AgentLoop` 跑 mini TAO 循环）、三个专用子 Agent（预约/咨询/行为分析）、`delegate` 工具与主 Agent 的自主派生决策；结果汇总回主 Agent，不硬编码路由。
- `skills`: 可复用能力的 Skill 声明（name/description/何时加载）与 `SkillRegistry` 按需加载机制，对齐 Claude Code skills；子 Agent 据任务按描述加载所需 skill 而非全量常驻。

### Modified Capabilities
- `agent-loop`: 主 `AgentLoop` 经 `delegate` 工具驱动子 Agent 派生（loop 本身不改语义，仅作为子 Agent 的复用执行体）；注入 `delegate` 后主 Agent 决策路由、子 Agent 执行领域工具。保持无状态、向后兼容（无 delegate 时行为同 Phase 6）。
- `tool-layer`: `ToolRegistry` 支持按子 Agent 构建工具子集（registry 切片/过滤），并新增 `delegate` 这一类「编排型工具」；既有工具与默认全量 registry 行为不变。

## Impact

- **新增代码**：`harness/subagents/`（`base.py` 子 Agent 抽象 + `appointment.py` / `consultant.py` / `user_behavior.py` 三个子 Agent + `delegate` 工具，一个概念一个文件）；`harness/skills/`（`Skill` + `SkillRegistry`）；`tests/` 新增子 Agent 派生 / delegate / skill 加载单测。
- **修改代码**：`harness/tools/registry.py`（支持子集构建 + 注册 delegate）；`harness/runtime/system_prompt.py`（主提示列出可派生子 Agent）；`api/chat_handler.py`（主 registry 接入 delegate）。
- **不碰保留资产**：`services/`、`db/`、`config/model_provider.py`、RAG（SQLite+FAISS）业务逻辑不重写；旧 `agents/` 仅作为参照、逐步废弃，不在本期删除以保兼容。
- **依赖方向**：subagents/skills 属 harness 层，向下复用 tools/services；不被下层反向依赖。子 Agent 派生共享 session_id 但各自独立上下文，互不污染。
- **成本/延迟**：delegate 会多一层 LLM 调用（主 Agent 决策 + 子 Agent 执行），由 Phase 5 token 预算与 Phase 6 延迟监控兜底；evals/ 端到端通过率须 ≥ 基线不回归。
