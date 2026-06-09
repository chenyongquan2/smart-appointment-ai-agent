## Context

经 Phase 0–6，harness 已有：`AgentLoop`（TAO 循环，[harness/runtime/agent_loop.py](../../../harness/runtime/agent_loop.py)）、`ToolRegistry` + 5 个薄封装工具、session 隔离 + 分层记忆、护栏、tracer。但主 Agent 仍是「单一 loop + 一个扁平 5 工具集 + 一段 system prompt」。Phase 7 要把领域能力沉淀为**专用子 Agent**，主 Agent 经 `delegate` 工具自主派生——对齐 Claude Code sub-agents / OpenClaw Skills。

关键复用资产（不重写）：`AgentLoop` 已是依赖注入式、无状态、可用 fake LLM 离线测；`ToolRegistry` 已支持注册/分发/导出 schema；`Tool` 四要素抽象。Phase 7 在这些之上做组合，不动 `services/`、`db/`、`config/model_provider.py`、RAG。

## Goals / Non-Goals

**Goals:**
- `SubAgent` 抽象：`name / description / 工具子集 / system prompt`，内部复用 `AgentLoop` 跑独立 mini 循环。
- 三个专用子 Agent（appointment / consultant / user_behavior），工具子集由全量 registry 切片得到。
- `delegate` 编排型工具 + 主 Agent system prompt 列出可派生子 Agent，由模型自主路由（消灭 if/else 路由）。
- `Skill` + `SkillRegistry` 按需加载机制。
- 全程离线可测（fake LLM）；evals/ 端到端 ≥ 基线不回归；无 `delegate` 时与 Phase 6 行为一致。

**Non-Goals:**
- 不删除旧 `agents/`（保留作参照，逐步废弃，避免破坏现有引用）。
- 不实现真正并行派生的并发执行（proposal 提到「可并行」，本期只做**串行**派生；并行留作后续，避免引入 asyncio 编排复杂度与共享状态竞争）。
- 不重写任何 service / DB / RAG / provider。
- 不引入新外部依赖。

## Decisions

### D1：`SubAgent` 复用 `AgentLoop` 而非新写循环
子 Agent = `AgentLoop(llm, subset_registry, system_prompt=专用)`。在 `harness/subagents/base.py` 定义 `SubAgent`（dataclass：name/description/tool_names/system_prompt），其 `run(task, session_id)` 用切片 registry 构造一个 `AgentLoop`、消费其 `[REPLY]` 流、返回纯文本。
- **为什么**：`AgentLoop` 已含护栏/tracer/错误隔离，重写会重复且易回归。
- **备选**：给子 Agent 单独写精简循环——被否，违反复用、双份护栏维护成本。
- **system_prompt 注入**：现 `AgentLoop.__init__` 内部 `build_system_prompt(registry)` 写死。需让 `AgentLoop` 接受可选 `system_prompt` 覆盖参数（缺省走 `build_system_prompt`，向后兼容）。这是对 runtime 的最小侵入式扩展。

### D2：工具子集用 `ToolRegistry` 切片
在 `ToolRegistry` 加 `subset(names) -> ToolRegistry`：复用既有 `Tool` 实例新建一个只含指定工具的 registry，未注册名报错。子 Agent 持有工具名列表，运行时从全量 registry 切片。
- **为什么**：单一真相源仍是全量 registry 注册表；切片不复制业务、不破坏 schema 导出。
- **备选**：每个子 Agent 各自 `build_xxx_registry()`——被否，工具实例会分散、重复 import。

### D3：`delegate` 是「编排型工具」，handler 不碰 services
`delegate` 在 `harness/subagents/delegate.py`（与子 Agent 同域，因其耦合子 Agent 注册表）。args schema：`subagent: str`（受限于已注册子 Agent 名）、`task: str`。handler 查子 Agent 注册表 → 调 `SubAgent.run` → 返回 `{success, subagent, result}`。未知 subagent 返回 `{success: False, error}`（不抛，靠 AgentLoop 错误回灌）。
- **为什么**：复用既有 Tool 抽象与 dispatch 路径，主 loop 无需任何特判；「主 Agent 决策、子 Agent 执行」自然落在 tool-calling 语义里。
- **子 Agent 注册表**：`SubAgentRegistry`（name → SubAgent），`delegate` 持有它的引用。`delegate` 需要构造子 Agent 的 `AgentLoop`，故需 llm + 全量 registry——通过工厂 `build_delegate_tool(llm, full_registry, subagent_registry)` 注入，避免模块级全局耦合。

### D4：主 Agent system prompt 显式列出子 Agent
扩展 `build_system_prompt`：当 registry 含 `delegate` 时，把可派生子 Agent 的 name+description 渲染进提示（显式优于隐式）。子 Agent 清单来源 = `SubAgentRegistry`。
- **备选**：把子 Agent 信息全塞进 `delegate.description`——可行但提示分散；选择在 system prompt 集中呈现「团队成员」更清晰。

### D5：Skills 最小实现，按需加载
`harness/skills/base.py` 定义 `Skill`（name/description/content）、`harness/skills/registry.py` 定义 `SkillRegistry.load_for(task) -> list[Skill]`（按 description 关键词/简单相关性匹配，可测）。本期作为可复用提示片段注入子 Agent system prompt 的扩展点；保持机制简单、显式、可断言。
- **为什么**：对齐 Claude Code「按需加载」理念，但不过度工程（本项目学习/面试用，见路线图风险节）。匹配先用确定性规则（关键词/标签），不引入向量检索，保证离线可测。

### D6：接线与向后兼容
`api/chat_handler.py`：构造全量 registry → 构造 `SubAgentRegistry`（三个子 Agent）→ `build_delegate_tool(...)` → 新建**主 registry**（含 delegate；主 Agent 不再直接持有领域工具，改为派生）→ 主 `AgentLoop`。`ProcessUserInput_stream` 签名、`[THOUGHT]/[REPLY]` 前缀、session/记忆注入全不变。

## Risks / Trade-offs

- **多层 LLM 调用抬高延迟/成本**（主决策 + 子执行）→ 复用 Phase 5 token 预算 + Phase 6 延迟监控；子 Agent 也受 `max_steps`/预算护栏约束。
- **端到端回归风险**（主 Agent 多绕一层可能丢历史/偏好上下文）→ evals/ 端到端通过率必须 ≥ 基线；子 Agent 透传 `session_id`；保留无 `delegate` 的全量路径作为对照与回退。
- **`AgentLoop` 加 `system_prompt` 参数的侵入**→ 设为可选、缺省走旧逻辑，加单测覆盖「缺省 == Phase 6 行为」。
- **子 Agent 上下文隔离 vs 记忆**：子 Agent 不持有主 Agent 完整历史，可能丢上下文 → delegate 的 `task` 由主 Agent 负责把必要上下文写进任务描述（主 Agent 已持有历史）。
- **Skills 匹配过于简单可能误加载/漏加载**→ 本期接受，规则确定性可测；后续可升级为语义匹配。

## Migration Plan

1. 加 `AgentLoop` 可选 `system_prompt` 参数（向后兼容）+ 单测。
2. 加 `ToolRegistry.subset()` + 单测。
3. 实现 `SubAgent` / `SubAgentRegistry` / 三个子 Agent + 单测（fake LLM）。
4. 实现 `delegate` 工具 + `build_delegate_tool` 工厂 + 单测。
5. 实现 `Skill` / `SkillRegistry` + 单测。
6. `build_system_prompt` 列出子 Agent + 单测。
7. 接线 `chat_handler.py`；跑 `uv run pytest` 与 evals/ 对照基线。
- **回滚**：主 registry 改回全量扁平工具集即恢复 Phase 6 行为（子 Agent/skills 代码可保留不接线）。

## Open Questions

- 无阻塞性未决项。并行派生与语义化 skill 匹配明确划为 Non-Goals / 后续迭代。
