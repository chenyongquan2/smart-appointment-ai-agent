## 1. AgentLoop 可选 system_prompt（运行时最小扩展）

- [x] 1.1 给 `harness/runtime/agent_loop.py` 的 `AgentLoop.__init__` 增加可选参数 `system_prompt: Optional[str] = None`；为 `None` 时仍走既有 `build_system_prompt(registry)`，传入时用该值覆盖。
- [x] 1.2 单测：缺省构造的 `AgentLoop` system prompt 与 Phase 6 一致（行为不变）；传入自定义 prompt 时生效。

## 2. ToolRegistry 工具子集切片

- [x] 2.1 在 `harness/tools/registry.py` 给 `ToolRegistry` 增加 `subset(names: list[str]) -> ToolRegistry`：复用既有 `Tool` 实例新建子集 registry；含未注册名时报错。
- [x] 2.2 单测：子集仅暴露指定工具、其 dispatch 与 schema 导出仅覆盖该工具；未注册名报错。

## 3. SubAgent 抽象与子 Agent 注册表

- [x] 3.1 新建 `harness/subagents/base.py`：`SubAgent`（dataclass：`name` / `description` / `tool_names` / `system_prompt`），`run(task, full_registry, llm, session_id=None) -> str`——用 `full_registry.subset(tool_names)` 构造 `AgentLoop`，消费 `[REPLY]` 流返回纯文本。
- [x] 3.2 新建 `harness/subagents/registry.py`：`SubAgentRegistry`（注册/按名查/列出；重名报错）。
- [x] 3.3 单测（fake LLM）：子 Agent 仅能调用其工具子集；上下文与主 Agent 隔离（中间步骤不外泄，仅返回最终文本）；触达护栏/工具异常时语义与顶层 loop 一致。

## 4. 三个专用子 Agent

- [x] 4.1 新建 `harness/subagents/appointment.py`：`appointment` 子 Agent，工具子集 = find_technician / check_availability / create_appointment / get_user_preferences，专用 system prompt。
- [x] 4.2 新建 `harness/subagents/consultant.py`：`consultant` 子 Agent，工具子集 = search_knowledge。
- [x] 4.3 新建 `harness/subagents/user_behavior.py`：`user_behavior` 子 Agent，工具子集 = get_user_preferences。
- [x] 4.4 单测：三个子 Agent 的工具子集正确（如 consultant 不含 create_appointment）；各自能在 fake LLM 下完成一次领域任务。

## 5. delegate 编排型工具

- [x] 5.1 新建 `harness/subagents/delegate.py`：`build_delegate_tool(llm, full_registry, subagent_registry) -> Tool`；args schema（`subagent: str` / `task: str`）；handler 查子 Agent → `SubAgent.run` → 返回 `{success, subagent, result}`；未知 subagent 返回 `{success: False, error}` 不抛。description 说明可派生子 Agent 选项。
- [x] 5.2 单测：合法派生转交对应子 Agent 并回传结果、不直接调 services；未知 subagent 返回结构化错误不崩。

## 6. Skills 按需加载

- [x] 6.1 新建 `harness/skills/base.py`：`Skill`（`name` / `description` / `content`）。
- [x] 6.2 新建 `harness/skills/registry.py`：`SkillRegistry`（注册/重名报错；`load_for(task) -> list[Skill]` 按描述关键词确定性匹配；无匹配返回空集不报错）。
- [x] 6.3 单测：按描述匹配加载相关 skill、未匹配不加载、无匹配返回空集、重名报错。

## 7. 主 system prompt 列出子 Agent

- [x] 7.1 扩展 `harness/runtime/system_prompt.py`：当主 registry 含 `delegate` 时，把可派生子 Agent 的 name+description 渲染进系统提示（来源 = SubAgentRegistry）。
- [x] 7.2 单测：含 delegate 时提示列出三个子 Agent 职责；不含时提示与既有一致。

## 8. 接线与回归验证

- [x] 8.1 改 `api/chat_handler.py`：构造全量 registry → SubAgentRegistry（三个子 Agent）→ build_delegate_tool → 主 registry（含 delegate）→ 主 `AgentLoop`；保持 `ProcessUserInput_stream` 签名、`[THOUGHT]/[REPLY]` 前缀、session/记忆注入不变。
- [x] 8.2 单测（fake LLM）：主 Agent 据任务调用 delegate 派生对应子 Agent，端到端产出回复；不含 delegate 的全量路径行为同 Phase 6。
- [x] 8.3 闸门 2：跑 `uv run pytest` 全绿；跑 `uv run python evals/run_evals.py`（如有 key）端到端通过率 ≥ 基线、不回归。成功静默、只报失败。
