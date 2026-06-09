## Why

当前 `agents/task_classification` 用「LLM 分类一次 → `if category == "appointment"` 硬路由」编排（`classification_processor.py:57`、`agent_router.py`），开发者必须预判所有分支，无法处理未预设的多步组合（如"约不到张三 → 自动查相似技师 → 直接约下一个有空的"）。这违背黄金准则「TAO 循环而非 if/else 路由」。Phase 2 已把 `services/` 封装为可被 LLM 调用的工具并建好 `ToolRegistry`，现在具备把决策方式从「写死流程」换成「模型在 loop 里自主决策」的前置条件。

## What Changes

- 新增 `harness/runtime/agent_loop.py`：一个 async TAO 循环——assemble context → LLM(bind tools) → 若无 tool_calls 则产出最终回复并结束；否则按名 dispatch 到 `ToolRegistry`、把工具结果作为 tool message 喂回，循环直到结束或触达 `max_steps` 上限。
- 新增 `harness/runtime/system_prompt.py`：harness 的系统提示（角色、可用工具语义、何时结束 loop），显式而非隐式。
- 新增 `harness/runtime/__init__.py`，导出 `AgentLoop`。
- `api/chat_handler.py` 的 `ProcessUserInput_stream` 切换为驱动新 `AgentLoop`，保留现有的流式 `yield` 接口与 `[THOUGHT]`/`[REPLY]` 前缀约定，调用方无需改动。loop 接口为 `session_id` 预留参数（Phase 4 才真正做会话隔离）。
- **BREAKING（内部）**：`agents/task_classification` 的 `ClassificationProcessor` + `AgentRouter` 不再是请求编排路径；由 `AgentLoop` 取代。`TaskClassifier`、`StateManager` 等组件本身保留（分类器可作为软提示/可选工具，状态可作软提示）。
- loop 内预留 trace 钩子点（`on_tool_call` / `on_observation` 的 no-op 默认实现），供 Phase 6 接入可观测；本 Phase 不实现 tracer。

不在本 Phase 范围（明确推迟）：会话隔离与记忆压缩（Phase 4）、重试/超时/权限护栏（Phase 5）、可观测 tracer 落地（Phase 6）。不重写 `services/`、`db/`、`config/model_provider.py`、RAG。

## Capabilities

### New Capabilities
- `agent-loop`: harness 运行时的 TAO 循环——用 native tool calling 驱动模型自主选择工具、把工具结果喂回并迭代，直至模型产出最终回复或触达步数上限；取代分类+硬路由作为请求编排核心。

### Modified Capabilities
<!-- 无。intent-classification / tool-layer 的需求不变（分类器与工具层保留）；
     被取代的 ClassificationProcessor/AgentRouter 路由层未被任何已有 spec 捕获，故无 delta。 -->

## Impact

- **新增代码**：`harness/runtime/`（`agent_loop.py`、`system_prompt.py`、`__init__.py`）。
- **修改代码**：`api/chat_handler.py`（编排入口切到 `AgentLoop`，保留流式接口）。
- **退役（保留文件、移出编排路径）**：`agents/task_classification/classification_processor.py`、`agent_router.py`。
- **复用（不改）**：`harness/tools/registry.py`（`build_default_registry` / `to_openai_schema` / async `dispatch`）、`config/model_provider.py`（`create_chat_model`，LangChain `BaseChatModel` 支持 `bind_tools`）。
- **测试/评估**：`tests/` 新增 loop 的离线确定性单测（fake `BaseChatModel`，不依赖 API key）；`evals/run_evals.py` 端到端通过率 ≥ Phase 0 基线（防回归）。
- **依赖**：无新增第三方依赖；沿用 LangChain 0.3.x 的 tool calling。
