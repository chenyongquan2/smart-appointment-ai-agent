# Project Learning Progress — Smart Appointment AI Agent

Last updated: 2026-06-21
Total: 0/47 mastered（H3、H6 已精读；H1、H2、H4 已通读；掌握计数待测评）

## Harness 架构知识域（重构后 · 配套 [docs/harness-code-reading.md](../../../docs/harness-code-reading.md) 的 7 站路线）

| 知识域 | 对应阅读站 / Phase | 已掌握 | 状态 |
|--------|-------------------|--------|------|
| H1 Agent Loop（TAO 循环 / 结束条件 / max_steps） | 第1站 · Phase 3 | 0/1 | 已学习（通读一遍） |
| H2 工具层（base/registry/schemas，薄封装 services） | 第2站 · Phase 1+2 | 0/1 | 已学习（通读 + 关联巩固：registry/schema/函数调用机制） |
| H3 上下文与分层记忆（session 隔离 / 短期+摘要+长期） | 第3站 · Phase 4 | 0/1 | 已精读（自顶向下重写 + 端到端调试验证） |
| H4 护栏（retry/budget/permission，错误隔离自愈） | 第4站 · Phase 5 | 0/1 | 已学习（通读一遍） |
| H5 可观测性（span/tracer/exporter 埋点） | 第5站 · Phase 6 | 0/1 | 未学习 |
| H6 子 Agent / Skills（delegate 派生 / 自主路由） | 第6站 · Phase 7 | 0/1 | 已精读（子 Agent 调用流程 + 调用栈图；Skills 概念/现状/选型辨析） |
| H7 端到端闭环 + 评估（e2e / evals / metrics） | 第7站 · Phase 0+6 | 0/1 | 未学习 |

> **进度口径**：「已掌握」以**测评打分**为准（见下方 Detailed History）；「已精读」= 已通过 [docs/harness-code-reading.md](../../../docs/harness-code-reading.md) 深度研读 + 断点调试，但**尚未测评**，故掌握计数仍为 0。
>
> - **2026-06-20**：精读 **H3 上下文与分层记忆**——把 3.x 各节改为「先为什么→实例→代码」自顶向下；澄清「LLM 无状态、每轮重拼 prompt」「短期喂回 / 长期注入 / 会话隔离」；新增并跑通 [`scripts/debug_memory_flow.py`](../../../scripts/debug_memory_flow.py) 端到端验证三层记忆。关联巩固 **H2**：registry（工具花名册）、单一真相源、**函数调用机制**（`tools` 字段经 `bind_tools` 才是模型能调工具的依据，系统提示里的工具清单基本冗余）。
> - **2026-06-21**：精读 **H6 子 Agent / Skills**。
>   - *子 Agent*：厘清「主 registry 只含 delegate、领域工具下沉子 Agent」「delegate 是工具不是子 Agent」「子 Agent ＝ 换装的主循环（复用同一 `AgentLoop.run`，只换 registry/system_prompt/出入口）」；画了 3 张图（结构 / 同核异端 / 真实调用栈，存 [`docs/img/subagent-call-stack.svg`](../../../docs/img/subagent-call-stack.svg)）。
>   - *Skills*：确认**本项目未接入**（骨架，同 `summary.py` stub）；系统梳理「要不要 / 何时 / 选型（`skills-ref` vs LangChain Deep Agents）/ `skills-ref` 成熟度（0.1.x 早期）/ 术语规范化（**Agent Skill** vs **Claude Code Skill** vs **harness 的 `Skill` 类**）」，汇总入 [`docs/skills-notes.md`](../../../docs/skills-notes.md)。
>   - *结论*：生产化阶段建议**移除 harness 的 `Skill` 骨架**（未接入、对未来生产版零复用）；真需要时采用开放 **Agent Skill** 标准。
> - **2026-06-21（补记）**：另**通读一遍 H1（Agent Loop）、H2（工具层）、H4（护栏）**，达「已学习」。说明档位：**已精读**（H3/H6，本会话深度研读+调试/辨析）＞ **已学习**（H1/H2/H4，通读一遍）＞ **已掌握**（均需测评打分，暂未做）。
>   - 待办：补学 **H5（可观测性）/ H7（端到端 + 评估）**；对已学的 H1–H4、H6 可做测评转「已掌握」。

## Domain Summary（原 agents 架构 · 业务领域，仍有效）

| 知识域 | 子知识点 | 已掌握 | 已学习 | 平均分 | 状态 |
|--------|----------|--------|--------|--------|------|
| D1 项目定位与整体架构 | 4 | 0/4 | 0/4 | - | 未学习 |
| D2 多 Agent 协作与任务分类 | 5 | 0/5 | 0/5 | - | 未学习 |
| D3 预约流程与状态管理 | 5 | 0/5 | 0/5 | - | 未学习 |
| D4 RAG 知识库与分块策略 | 5 | 0/5 | 0/5 | - | 未学习 |
| D5 技师推荐与 Embedding/FAISS | 4 | 0/4 | 0/4 | - | 未学习 |
| D6 用户行为学习与主动推荐 | 4 | 0/4 | 0/4 | - | 未学习 |
| D7 API/Web/流式响应与延迟 | 4 | 0/4 | 0/4 | - | 未学习 |
| D8 数据库与持久化 | 4 | 0/4 | 0/4 | - | 未学习 |
| D9 模型配置、框架选型与工程化 | 5 | 0/5 | 0/5 | - | 未学习 |

## Detailed History

| # | Date | 知识点 ID | 知识点 | 题源 | 问题 | 评分 | 追问轮数 | 薄弱点 |
|---|------|-----------|--------|------|------|------|----------|--------|