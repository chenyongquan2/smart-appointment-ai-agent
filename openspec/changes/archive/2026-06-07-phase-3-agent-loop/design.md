## Context

请求编排现状（被替换的路径）：
- `api/chat_handler.py::ProcessUserInput_stream` → `TaskClassificationAgent.classify_task_stream` → `ClassificationProcessor.process_task_stream`（`classification_processor.py:57`）：先 `classify_task` 得到意图字符串，再 `if category == "appointment" / "query"` 硬路由到 `AgentRouter.route_to_appointment / route_to_consultation`，否则不支持。状态由 `StateManager` 持有，后续轮按状态续走。
- 这是「开发者写死流程」：分支必须预判，无法处理"约不到就换人"这类未预设组合。

已具备的前置（Phase 2，复用不改）：
- `harness/tools/registry.py`：`build_default_registry()` 注册 5 个工具；`to_openai_schema()` 导出 OpenAI function-calling 格式；`async dispatch(name, raw_args)` 用 Pydantic 校验后执行 handler。
- `config/model_provider.py::create_chat_model()` 返回 LangChain `BaseChatModel`（Azure/OpenAI-compatible），支持 `bind_tools(...)`。
- `evals/run_evals.py` + `tests/` 离线安全网（Phase 0）。

约束：黄金准则（TAO 而非 if/else、结构化输出、一个概念一个文件、单向依赖、薄封装）；不重写 `services/`/`db/`/`model_provider`/RAG；测试须离线确定性（无 API key）。

## Goals / Non-Goals

**Goals:**
- 新建 `harness/runtime/agent_loop.py`，用 native tool calling 的 TAO 循环取代分类+硬路由。
- loop 可注入 LLM 与 registry，离线 fake LLM 即可确定性单测全部分支。
- `max_steps` 防失控；工具失败回灌错误不崩；保留流式 `yield` 与 `[THOUGHT]/[REPLY]/[ERROR]` 前缀。
- 为 `session_id` 预留接口参数；为 Phase 6 预留 trace 钩子点。

**Non-Goals:**
- 会话隔离 / 记忆压缩（Phase 4）；重试 / 超时 / 权限护栏（Phase 5）；tracer 落地（Phase 6）。
- 不改工具内部逻辑、不改 services/db/RAG/model_provider。
- 不引入新框架（不在本 Phase 上 LangGraph；保持原生手写 loop 以最大化对原理的掌握）。

## Decisions

### D1：原生手写 loop，而非 LangGraph
用 LangChain `BaseChatModel.bind_tools()` + 手写 while 循环。理由：路线图第 4 节建议学习阶段先手写一遍最懂原理；本项目工具仅 5 个、状态简单，LangGraph 的检查点/可视化收益不抵其复杂度。LangGraph 留作 Phase 4 状态图的可选项。

### D2：消息协议用 LangChain message 对象
loop 内维护 `list[BaseMessage]`：`SystemMessage`（系统提示）→ `HumanMessage`（用户输入）→ `AIMessage`(含 `tool_calls`) → `ToolMessage`(含 `tool_call_id`)。用 `llm.bind_tools(tools)` 让模型按协议返回 `tool_calls`，避免任何字符串解析（黄金准则）。tools schema 直接取自 `registry`（OpenAI 格式的 function-calling 已被 LangChain `bind_tools` 接受；也可直接传 Pydantic/Tool 对象列表——实现时取 registry 暴露的可绑定形式）。

### D3：循环骨架
```
async def run(self, user_input, session_id=None):
    messages = [SystemMessage(system_prompt), HumanMessage(user_input)]
    for step in range(self.max_steps):
        ai = await self.llm_with_tools.ainvoke(messages)
        messages.append(ai)
        if not ai.tool_calls:
            yield ai.content; return          # 最终回复，结束
        for call in ai.tool_calls:
            self._on_tool_call(call)           # Phase 6 trace 钩子(默认 no-op)
            try:
                result = await self.registry.dispatch(call["name"], call["args"])
            except Exception as e:
                result = f"工具执行失败: {e}"    # 回灌错误，不崩(spec: 工具失败不崩循环)
            self._on_observation(result)
            messages.append(ToolMessage(str(result), tool_call_id=call["id"]))
    yield self._fallback_reply()               # 触达 max_steps 的兜底
```
- 钩子 `_on_tool_call` / `_on_observation` 默认 no-op，构造时可注入，供 Phase 6。
- 流式：本 Phase 先用 `ainvoke`（非 token 级流式），在最终回复处一次性 `yield`，保持 `ProcessUserInput_stream` 的 async generator 契约；token 级 streaming 可后续增强（不在验收内）。

### D4：系统提示独立文件 `harness/runtime/system_prompt.py`
显式声明角色（按摩门店预约/咨询助手）、可用工具语义、何时结束（已能回答或已完成预约即直接回复、不要无谓调用工具）。一个概念一个文件。

### D5：接入点 `ProcessUserInput_stream` 切到 `AgentLoop`
保留签名 `(user_input, state=None, context=None)` 与 async generator 流式输出。内部构造（或复用模块级）`AgentLoop(llm=create_chat_model(), registry=build_default_registry())` 并 `async for token in loop.run(user_input): yield token`。`[THOUGHT]/[REPLY]` 前缀：最终回复包一层 `[REPLY]` 前缀以兼容前端解析约定（按现有前端实际约定决定）。

### D6：退役而非删除旧路由
`ClassificationProcessor` / `AgentRouter` 文件保留（避免大爆炸式删除、便于回滚），仅从编排路径移除。`TaskClassifier` 保留——可作为 loop 的软提示来源或后续作为一个可选工具；本 Phase 不强制把它做成工具。

## Risks / Trade-offs

- [Provider 对 tool calling 的兼容差异] → 用 LangChain `bind_tools` 抽象屏蔽；Azure/OpenAI-compatible 均支持。单测用 fake LLM 不触网。
- [非 token 级流式，首字延迟变长] → 本 Phase 接受；token 级 streaming 列为后续增强，不在验收内。
- [loop 多次调 LLM → 成本/延迟上升] → `max_steps` 兜底；成本监控留 Phase 5/6。
- [评估集只测意图分类，无法直接度量 loop 端到端] → 验收以「`evals` 通过率 ≥ 基线 + 新增 loop 离线单测覆盖四类路径」双重保证；端到端 eval 增强留后续。
- [前端 `[THOUGHT]/[REPLY]` 前缀约定耦合] → 实现时核对现有前端解析，保持前缀语义不破坏。

## Migration Plan

1. 新增 `harness/runtime/`（loop + system_prompt + `__init__`）与单测，先独立可测、不接线。
2. 单测全绿后，把 `ProcessUserInput_stream` 切到 `AgentLoop`。
3. 跑 `uv run pytest` + `uv run python evals/run_evals.py` 对照基线。
4. 回滚策略：旧 `ClassificationProcessor/AgentRouter` 仍在，`chat_handler.py` 一行切回即可恢复旧路径。

## Open Questions

- 前端对最终回复的前缀解析（是否必须 `[REPLY]` 包裹、`[THOUGHT]` 是否需要逐步输出）——实现时按现有 `web/` 约定核对，不破坏既有渲染。
- `TaskClassifier` 是否在本 Phase 顺带包装为一个工具——倾向不做（超出 Phase 3 范围），留作后续。
