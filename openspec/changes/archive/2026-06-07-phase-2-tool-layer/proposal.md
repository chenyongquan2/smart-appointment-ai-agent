## Why

当前 `agents/` 层把 `services/` 的能力藏在 if/else 路由和字符串信号背后，LLM 无法把它们当作可调用的工具来自主编排。要走向 harness（Phase 3 的 agent loop 依赖一个可被模型调用的工具层），必须先把 `services/` 的核心能力包装成统一注册、带 schema、可按名分发的 **tools**。这是 `docs/harness-refactor-plan.md` 的 Phase 2，承接已完成的 Phase 1（结构化输出）。

## What Changes

- 新建 `harness/tools/` 包：**一个工具一个文件**，每个工具声明 `name` / `description` / `args schema`（Pydantic v2）/ `handler`。
- 包装 5 个工具（薄封装，内部调用既有 `services/`，**不重写业务逻辑**）：
  - `search_knowledge(query, top_k)` → `KnowledgeService.search`
  - `find_technician(start_time, duration, project, preference, gender, technician_name)` → `TechnicianService` / `AppointmentService`
  - `check_availability(technician_id, start_time, end_time)` → `AppointmentService.is_technician_available`
  - `create_appointment(...)` → `AppointmentService.save_appointment`
  - `get_user_preferences(user_id)` → `UserBehaviorService.get_user_preferences` / `analyze_user_patterns`
- 新建 `ToolRegistry`：统一注册工具、导出给 LLM 的 tools schema（Anthropic 与 OpenAI 两种格式）、按 `name` 分发（dispatch）参数到对应 handler。
- 工具返回**结构化结果**（Pydantic / dict），而非裸字符串。
- 不改动 `agents/` 现有路由（Phase 3 才接线）；本 Phase 仅新增可独立单测的工具层。

## Capabilities

### New Capabilities
- `tool-layer`: 把 `services/` 能力暴露为 LLM 可调用工具的统一抽象——工具定义（name/description/args schema/handler）、ToolRegistry 注册与按名分发、以及导出 Anthropic/OpenAI tools schema 的契约。

### Modified Capabilities
<!-- 无：本 Phase 不修改既有 spec 的行为，仅新增工具层能力。 -->

## Impact

- **新增**：`harness/` 包（`harness/tools/`、`harness/tools/registry.py`、各工具文件、共享 args schema）。
- **新增**：`tests/` 下工具与 registry 的单测；可选在 `evals/` 增补工具调用相关样本。
- **依赖**：复用 Phase 1 的 `AppointmentSlots`（`agents/appointment/schemas.py`）思路，新增工具入参 schema。
- **不动（保留资产）**：`services/`、`db/`、`config/model_provider.py`、RAG（FAISS+SQLite）。依赖方向严格单向向下：`harness/tools/` → `services/`，services 不反向 import harness。
- **无破坏性变更**：现有 `agents/` 路由与 API 行为不变。
