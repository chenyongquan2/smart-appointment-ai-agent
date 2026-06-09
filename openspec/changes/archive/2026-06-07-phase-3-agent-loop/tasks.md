## 1. runtime 骨架

- [x] 1.1 新建 `harness/runtime/__init__.py`，导出 `AgentLoop`
- [x] 1.2 新建 `harness/runtime/system_prompt.py`：定义 harness 系统提示（角色=按摩门店预约/咨询助手、可用工具语义、何时结束 loop 的指引），作为常量/构造函数导出

## 2. AgentLoop 核心（TAO 循环）

- [x] 2.1 新建 `harness/runtime/agent_loop.py`：`AgentLoop` 接受注入的 `llm`（LangChain `BaseChatModel`）、`registry`（`ToolRegistry`）、`max_steps`、可选 trace 钩子；构造时用 `llm.bind_tools(...)` 绑定 registry 导出的工具
- [x] 2.2 实现 `async run(self, user_input, session_id=None)`：组装 `[SystemMessage, HumanMessage]`，进入 `for step in range(max_steps)` 循环
- [x] 2.3 每步 `await llm_with_tools.ainvoke(messages)`：无 `tool_calls` 则 `yield` 最终回复并 return（spec: 无工具调用时直接产出最终回复）
- [x] 2.4 有 `tool_calls` 则逐个 `await registry.dispatch(name, args)`，结果以 `ToolMessage(tool_call_id=...)` 喂回（spec: 工具结果按协议喂回 / 多个并行调用全部喂回）
- [x] 2.5 dispatch 包 try/except：异常时把错误描述作为该 tool_call_id 的 ToolMessage 喂回、继续循环，不崩（spec: 工具失败不崩循环）
- [x] 2.6 触达 `max_steps` 仍未结束：产出安全兜底回复（spec: 步数上限防失控）
- [x] 2.7 预留 `_on_tool_call` / `_on_observation` 钩子，默认 no-op，可注入（Phase 6 trace 钩子点）

## 3. 接入编排入口

- [x] 3.1 `api/chat_handler.py::ProcessUserInput_stream` 切换为驱动 `AgentLoop`（`create_chat_model()` + `build_default_registry()`），保留 `(user_input, state=None, context=None)` 签名与 async generator 流式 `yield`
- [x] 3.2 保持 `[THOUGHT]/[REPLY]/[ERROR]` 前缀语义：核对 `web/` 前端解析约定，最终回复包 `[REPLY]` 前缀，不破坏既有渲染
- [x] 3.3 把 `ClassificationProcessor` / `AgentRouter` 移出编排路径（保留文件，便于回滚）；确认 `agents/` 不被新路径反向依赖

## 4. 离线确定性单测

- [x] 4.1 在 `tests/` 写一个 fake `BaseChatModel`（`ScriptedChatModel`），按预设脚本返回「带 tool_calls 的 AIMessage」与「最终文本 AIMessage」，不触网
- [x] 4.2 测试：直接回复路径（无 tool_calls → 立即产出回复）
- [x] 4.3 测试：单步工具路径（一次 tool_call → dispatch → 喂回 → 最终回复）
- [x] 4.4 测试：多步组合路径（连续两步不同工具调用 + 同一步多调用全部喂回）
- [x] 4.5 测试：`max_steps` 上限生效（始终返回 tool_calls → 达上限产出兜底、不无限循环）
- [x] 4.6 测试：工具 dispatch 抛异常 → 错误被回灌、循环继续不崩

## 5. 验证（闸门 2）

- [x] 5.1 `uv run pytest` 全绿（48 passed, 9 xfailed；新增 7 条 loop 单测 + 既有安全网不回归）
- [x] 5.2 `uv run python evals/run_evals.py`：意图通过率 19/20 (95.0%) ≥ Phase 0 基线（分类器未改，不回归）
- [x] 5.3 核对验收标准：TAO 循环取代 if/else ✅、多步组合 ✅、max_steps 生效 ✅、离线确定性可测 ✅——逐条达成
