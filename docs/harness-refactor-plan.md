# 从 Workflow 到 Harness：Smart Appointment Agent 重构计划

> 📍 本文属于 harness 学习系列（**第 3 步 · 动手重构**）。总览见 [harness-index.md](./harness-index.md)。
>
> 目标：把当前"LLM 分类 + if/else 硬路由"的工作流，重构为一个真正的 **Agent Harness**（智能体运行时外壳），对齐 2026 年主流实践，参考 **Claude Code** 与 **OpenClaw** 的架构。
>
> 核心理念：**模型负责推理（reasoning），harness 负责能力（capability）**。投资 harness，而非只换模型。

---

## 0. 现状诊断（为什么要改）

当前 `agents/` 层本质是一个硬编码工作流，不是 harness：

| 维度 | 现状 | 代码位置 |
|------|------|----------|
| 编排 | `if category=="appointment"` 一次性路由，无循环 | `agents/task_classification/classification_processor.py:57` |
| 工具调用 | LLM 吐字符串，再人工 `if` 匹配 | `agents/task_classification/task_classifier.py:66` |
| 结构化 | `content.strip().lower()` + 白名单 | `task_classifier.py:66-71` |
| 状态 | 全局单实例、单 session、会串号 | `api/chat_handler.py:7-12` |
| 记忆 | 仅一个状态枚举 + 内存历史 | `config/constants.py`, `agents/appointment_agent.py:50` |
| 组件通信 | 字符串信号 `[SIGNAL]xxx` | `agents/appointment_agent.py:126` |
| 护栏 | 仅 try/except | 各 agent |
| 可观测性 | `print("[DEBUG]")` | `task_classification_agent.py:83` |

**保留**（这些设计是对的，不动）：五层分层架构、`services/` 业务逻辑、`db/` Repository、`config/model_provider.py` 的 Provider 抽象。

> 📌 **本地 RAG 已于 2026-08-02 移除**（change `remove-local-rag`）：原文这里还列着「RAG 的 SQLite+FAISS 基础」作为保留项，但知识库后续由一个**独立的 RAG 项目**承担，本仓只留 [services/knowledge_search.py](../services/knowledge_search.py) 的可替换端口。FAISS 依赖仍在，服务的是技师专长相似度匹配。

**替换**：`agents/` 这一层 —— 从"分类+路由"换成"harness（agent loop + tools + memory + guardrails + observability）"。

---

## 1. 目标架构（Harness 蓝图）

对齐 OpenClaw 七组件 / Claude Code 架构，映射到本项目：

```
┌─────────────────────────────────────────────────────────┐
│  Channel / Gateway   ← 已有：FastAPI + web/ (小改：带 session_id) │
├─────────────────────────────────────────────────────────┤
│  Agent Runtime (新核心)                                    │
│    ┌──────────────────────────────────────────────┐      │
│    │  Agent Loop (TAO / ReAct)                      │      │
│    │   assemble context → LLM(tools) → dispatch     │      │
│    │   tool → observe → repeat until done           │      │
│    └──────────────────────────────────────────────┘      │
│         │              │              │                    │
│   Tool Registry   Context Mgr   Guardrails                 │
│   (function        (system+      (timeout/retry/           │
│    calling schema)  memory+       schema validate/         │
│                     history)      permission)              │
├─────────────────────────────────────────────────────────┤
│  Memory & Knowledge  ← 改：session 隔离 + 持久化 + 长期偏好    │
├─────────────────────────────────────────────────────────┤
│  Tools → Services    ← 包装已有 services/ 为工具             │
│    search_knowledge / find_technician / check_availability │
│    / create_appointment / get_user_preferences            │
├─────────────────────────────────────────────────────────┤
│  LLM Provider        ← 已有：config/model_provider.py        │
├─────────────────────────────────────────────────────────┤
│  Observability (新)  ← trace：thought / tool_call / result   │
└─────────────────────────────────────────────────────────┘
```

**关键转变**：
- 现在是"**开发者写死流程**"，预判所有分支。
- harness 是"**模型在 loop 里自主决定流程**"，能处理未预设的组合（如"约不到张三 → 自动查相似技师 → 直接约下一个有空的"）。

---

## 2. 分阶段重构路线（7 个里程碑）

> 原则：**每个阶段可独立交付、可回滚、有验收标准**。不要一次性推倒重来。

### Phase 0 — 准备：安全网与基线（0.5 天）
**目标**：改之前先有"测试网"和"对照基线"，否则重构会引入回归。
- 跑通现有 `tests/`，记录当前行为作为黄金样本。
- 建一个 `evals/` 目录，写 ~20 条评估用例（输入 → 期望意图/期望工具调用），作为重构前后对照。
- 引入最简 trace：先用结构化 `logging`（JSON）替换 `print`，记录每步 input/output。
- **验收**：能一键跑评估集，输出当前准确率基线。
- **技能点**：评估驱动开发（eval-driven）。

### Phase 1 — 结构化输出（1 天）⭐ 性价比最高，先做
**目标**：消灭所有"字符串解析"，为 native tool calling 打基础。
- 定义 Pydantic 模型：`TaskCategory`、`AppointmentSlots`（gender/start_time/duration/project/preference/technician）。
- `TaskClassifier` 改用 **structured output / function calling**，强制模型返回合法 JSON，删掉 `strip().lower()` + 白名单兜底。
- `InputParser`（`agents/appointment/input_parser.py`）同样改为 schema 约束抽取。
- **改的文件**：`task_classifier.py`、`appointment/input_parser.py`。
- **验收**：评估集上分类/抽取的格式错误率降到 0。
- **技能点**：function calling、Pydantic schema、structured output。
- **简历话术**：用结构化输出替代字符串解析，意图识别与槽位抽取可靠性显著提升。

### Phase 2 — 工具层抽象（1.5 天）
**目标**：把 `services/` 的能力包装成 LLM 可调用的 **tools**。
- 新建 `harness/tools/`，每个工具一个文件，含 name / description / args schema / handler。
- 工具清单（薄封装，内部调 services/，不重写业务）：
  - `search_knowledge(query, top_k)` → ~~`KnowledgeService`~~ → 现为 `KnowledgeSearchPort`（本地 RAG 已移除，见上文 §0 的注）
  - `find_technician(time, project, preference, gender)` → `TechnicianFinder`/`technician_service`
  - `check_availability(technician_id, time)` → `appointment_service`
  - `create_appointment(slots)` → `appointment_service`
  - `get_user_preferences(user_id)` → `user_behavior_service`
- 建 `ToolRegistry`：统一注册、生成给 LLM 的 schema、按名分发。
- **验收**：每个工具可单测调用；ToolRegistry 能导出 OpenAI/Anthropic 格式的 tools schema。
- **技能点**：工具设计、关注 description 质量（harness 里工具描述就是"给模型的说明书"）。

### Phase 3 — Agent Loop（2 天）🎯 核心
**目标**：用 TAO 循环替换 `if/else` 路由。
- 新建 `harness/runtime/agent_loop.py`：
```python
async def run(self, messages, session):
    for step in range(self.max_steps):           # 防失控上限
        resp = await self.llm.ainvoke(messages, tools=self.registry.schemas())
        if not resp.tool_calls:                   # 模型给出最终回复
            yield resp.content
            return
        for call in resp.tool_calls:
            self.tracer.on_tool_call(call)        # 可观测
            result = await self.registry.dispatch(call, session)  # 执行
            messages.append(tool_result(call.id, result))         # 喂回
            self.tracer.on_observation(result)
```
- 系统提示里写清角色、可用工具、何时结束。
- 用它替换 `ClassificationProcessor` + `AgentRouter` 的硬路由。`StateManager` 的状态可保留为"软提示"或迁移为 LangGraph 节点（见下）。
- **可选**：用 **LangGraph** 把流程显式建成状态图（你已有 StateManager 思路，迁移自然），获得断点续跑、可视化、检查点。
- **验收**：评估集端到端通过率 ≥ 基线；能处理"约不到就换人"这类多步组合。
- **技能点**：ReAct/TAO loop、agent 编排、（可选）LangGraph。
- **简历话术**：将 if/else 路由重构为工具调用驱动的 agent loop，支持多步自主决策。

### Phase 4 — 状态与记忆（1.5 天）
**目标**：解决全局串号，建真正的记忆层。
- `chat_handler.py` 的全局单实例 → 按 `session_id` 隔离（`Dict[session_id, SessionState]` 或 Redis）。
- 请求体带 `session_id`/`conversation_id`；`ProcessUserInput_stream` 真正使用 `state`/`context`（现在被忽略）。
- 记忆分层：
  - **短期**：对话窗口（最近 N 轮）。
  - **摘要**：超出窗口时压缩为摘要（对齐 Claude Code 的 context compaction）。
  - **长期**：用户偏好（已有 `UserPreference`/`PreferenceManager`），跨会话读取。
- 持久化到 DB，重启不丢。
- **验收**：两个 session 并发互不干扰；重启后能恢复会话。
- **技能点**：会话隔离、context engineering、记忆压缩。
- **📌 记忆压缩后续升级**（OpenSpec change `add-context-compaction`，2026-06-21）：Phase 4 的摘要层当时留 `NoOpSummary` 占位桩，已升级为**生产级实现** `LLMSummaryMemory`——固定 token 阈值触发（不锚模型窗口）、结构化滚动压缩（summary-of-summary）、`ConversationSummary` 表持久化缓存（`covered_upto`=末条 turn id）、读/写分离（写侧回合收尾 inline-after-stream 算、读侧请求开始纯读缓存）、LLM 失败降级回纯窗口、tracer 可观测。选型依据见 [harness-study-notes.md §9](./harness-study-notes.md)（Claude Code 高水位全量 vs 滚动缓冲摘要两流派）。后续 change `fix-compaction-gap-blindspot` 又修掉了「夹缝盲区」——把读侧可见性分界从窗口改为 `covered_upto`（未压缩回合一律原文注入），详见学习笔记 §9.5。
- **简历话术**：重构全局状态为按会话隔离 + 分层记忆，支持并发用户与跨会话偏好。

### Phase 5 — 护栏 Guardrails（1 天）
**目标**：让 harness 在生产环境可信。
- LLM 调用：超时、重试（指数退避）、限流。
- 工具调用：参数 Pydantic 校验、白名单、危险操作（如 `create_appointment`）需确认或权限检查。
- Loop：`max_steps` 上限、死循环检测、token 预算。
- 错误隔离：单个工具失败不崩整个 loop，回灌错误让模型自愈。
- **验收**：注入坏输入/超时/工具异常，harness 不崩、能优雅降级。
- **技能点**：可靠性工程、权限模型（对齐 Claude Code permission modes）。

### Phase 6 — 可观测性与评估闭环（1 天）
**目标**：能看见、能度量、能复盘。
- 接入 **LangSmith** 或 **OpenTelemetry**：全链路 trace（thought / tool_call / observation / latency / tokens）。
- 指标：意图准确率、工具调用正确率、槽位抽取完整率、RAG 命中率、首 token 延迟、端到端延迟、任务成功率。
- 坏 case 回流：失败/用户纠正 → 落库 → 补充评估集或知识库。
- **验收**：每次请求可在 trace UI 回放；评估集自动出报告。
- **技能点**：可观测性、eval 体系（直接答 RQ06/RQ11/RQ12）。

### Phase 7 — 子 Agent / Skills 化（进阶，2 天，可选）
**目标**：对齐 Claude Code 的 sub-agents 与 OpenClaw 的 Skills System。
- 把"预约""咨询""行为分析"做成**专用子 Agent**，由主 harness 通过一个 `delegate(sub_agent, task)` 工具派生调用（而非硬编码路由）。
- 复杂任务可并行派生、各自独立上下文，结果汇总回主 Agent。
- ~~可选：把可复用能力沉淀为 **Skill**（带描述、按需加载），对齐 Claude Code skills 机制。~~ → **已撤销**：Phase 7 曾搭关键词版 Skill 骨架，但从未接入运行路径，已于 2026-06-21 移除（PR #2，YAGNI）；真要做按开放 `SKILL.md` 标准重做，理由见 [skills-notes.md §8](./skills-notes.md)。
- **验收**：主 Agent 能自主决定"这个任务交给哪个子 Agent"。
- **技能点**：multi-agent orchestration、sub-agent 派生、skills 设计。

---

## 3. 目录结构演进

```
harness/                      # 新增：harness 核心
├── runtime/
│   ├── agent_loop.py         # TAO 循环
│   ├── context_manager.py    # 上下文组装 + 记忆压缩
│   └── session.py            # 按 session 的状态
├── tools/
│   ├── registry.py           # ToolRegistry
│   ├── knowledge.py          # search_knowledge
│   ├── technician.py         # find_technician / check_availability
│   ├── appointment.py        # create_appointment
│   └── preference.py         # get_user_preferences
├── guardrails/
│   ├── retry.py / timeout.py / validate.py / permission.py
├── memory/
│   ├── short_term.py / summary.py / long_term.py
└── observability/
    └── tracer.py

services/   # 保留：工具内部调用它
db/         # 保留
config/     # 保留（model_provider 直接复用）
agents/     # 逐步废弃 / 迁移为 harness/tools + sub-agents
evals/      # 新增：评估集
```

---

## 4. 框架选型建议

| 选项 | 适用 | 备注 |
|------|------|------|
| **原生 SDK agent loop**（Anthropic/OpenAI） | 想彻底理解 harness 原理 | 推荐学习用，控制力最强 |
| **LangGraph** | 想要状态图、检查点、可视化 | 与你现有 StateManager 思路契合，迁移自然 |
| **Microsoft Agent Framework** | 想参考企业级 Agent Harness | 2026 BUILD 专门讲了 harness |

学习阶段建议**原生 SDK 手写一遍 loop**（最懂原理），生产化再考虑 LangGraph。

---

## 5. 风险与取舍

- **不要一次性重写**：按 Phase 增量替换，每步对照评估集，随时可回滚。
- **成本上升**：tool-calling loop 会多次调用 LLM，延迟和费用上升 → Phase 5 的 token 预算 + Phase 6 的延迟监控要跟上。
- **过度工程**：本项目是学习/面试用，不必复刻 Claude Code 全部能力（hooks、MCP、多 IDE 集成等）。**Phase 1–4 就已是一个合格 harness**，5–7 按精力做。
- **保留业务资产**：services/db/RAG 不重写，harness 只是换了"大脑的决策方式"。

---

## 6. 学习与面试映射

| Phase | 现代技能 | 对应面试题 |
|-------|----------|-----------|
| 1 | function calling / structured output | RAG/可靠性 |
| 2 | 工具设计 | 多 Agent / 工具 |
| 3 | agent loop / ReAct | RQ08/RQ09/RQ15（多 Agent 编排） |
| 4 | 会话隔离 / context engineering | 记忆、并发 |
| 5 | 护栏 / 权限 | 工程化、可靠性 |
| 6 | 可观测性 / eval | RQ06/RQ10/RQ11/RQ12 |
| 7 | sub-agent / skills | 多 Agent 高阶 |

**一句话简历定位（改造后）**：
> "将一个硬编码的多模块预约工作流，重构为基于 tool-calling 循环的 Agent Harness：定义结构化工具层、按会话隔离的分层记忆、护栏与全链路 trace，对齐 Claude Code / OpenClaw 的 harness 架构。"

---

## 7. 建议起步顺序

**Phase 0 → Phase 1**。先有评估网，再做结构化输出（改动小、收益大、是 tool calling 的前置）。把 Phase 1 跑通并在评估集上验证后，你就真正理解了 harness 的"工具层"，再推进 Phase 2/3 的 loop。

---

### 参考
- Claude Code（agent loop + tools + sub-agents + skills + permissions + context compaction）
- OpenClaw 七组件架构（Channel / Gateway / Skills / Agent Runtime / Memory / LLM Provider / Execution）
- Anthropic context engineering、Microsoft Agent Framework (BUILD 2026)
