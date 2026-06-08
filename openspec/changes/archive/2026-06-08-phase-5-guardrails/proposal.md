## Why

harness 的 TAO 循环目前裸调用 LLM 与工具：`AgentLoop` 直接 `await self.llm.ainvoke(...)`（`harness/runtime/agent_loop.py:92`），LLM 一次超时/抖动就会让整轮请求挂起或抛栈;危险写操作 `create_appointment` 与只读查询同权限、无任何确认或拦截;循环只有 `max_steps` 这一个上限，无 token 预算、无原地打转检测。要让 harness 在生产环境可信（Phase 5 目标），必须补齐"超时/重试/预算/权限"这层护栏。

## What Changes

- 新增 `harness/guardrails/` 护栏层（一个概念一个文件），harness 内的薄封装，**不触碰** `services/`、`db/`、`config/model_provider.py`、RAG。
- **LLM 调用护栏**：`AgentLoop` 的 `ainvoke` 经一层超时 + 指数退避重试包裹;超时/重试耗尽后不抛栈，按既有 `[REPLY]` 兜底语义优雅降级。
- **危险操作权限**：工具声明 `dangerous` 标记;`create_appointment` 标为危险，dispatch 前经权限闸门(默认放行但可拒绝/要求确认的可注入策略)，被拒时把结构化拒绝结果回灌给模型(沿用既有错误回灌路径，不崩 loop)。
- **Loop 预算护栏**：在既有 `max_steps` 之外，增加累计 token 预算上限与"连续相同工具调用"的打转检测;触达即按兜底回复优雅收尾。
- **错误隔离校验**：为既有"单工具失败回灌不崩 loop"（`agent_loop.py:113`）补回归测试，纳入护栏验收。

## Capabilities

### New Capabilities
- `guardrails`: harness 的可靠性护栏——LLM 调用超时/重试、危险工具操作的权限闸门、循环 token 预算与打转检测、以及统一的优雅降级行为。

### Modified Capabilities
- `agent-loop`: 循环在 `max_steps` 外新增 token 预算与打转检测终止条件;LLM 调用与工具分发改为经护栏执行（行为：注入超时/异常/坏输入时不崩、优雅降级）。
- `tool-layer`: `Tool` 新增 `dangerous` 标记;`ToolRegistry.dispatch` 在执行 handler 前经权限闸门，危险工具可被策略拒绝。

## Impact

- **新增**：`harness/guardrails/`（如 `retry.py` / `timeout.py` / `permission.py` / `budget.py`，按设计定稿）；对应 `tests/`。
- **修改**：`harness/runtime/agent_loop.py`（经护栏包裹 LLM 调用、增加预算/打转终止）、`harness/tools/base.py`（`dangerous` 字段）、`harness/tools/registry.py`（dispatch 前权限闸门）、`harness/tools/appointment.py`（标记危险）。
- **不动**：`services/`、`db/`、`config/model_provider.py`、RAG（SQLite+FAISS）——护栏只在 harness 层。
- **验证**：`uv run pytest` 与 `evals/` 必须绿;新增坏输入/超时/工具异常/权限拒绝的注入测试。
