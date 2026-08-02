# Skill 学习笔记（概念 / 现状 / 是否需要 / 选型 / 成熟度）

> 整理日期：2026-06-21。配套 [harness-code-reading.md](./harness-code-reading.md) 第 6 站 6.5。
> 本文汇总围绕「Skill」的全部讨论与结论，供将来判断「该不该上 skill、上哪个」时直接查。

---

## 0. 先分清三个被叫做「skill」的东西（读本文前必看）

「skill」这个词被混用成几个不同层面的东西，混着读就会觉得「它们好像没区别」。先分清：

| 记号 | 指的是 | 关键点 |
|---|---|---|
| **#1 理念** | 「按需加载可复用能力、不常驻」（渐进式披露） | **这一层大家都一样**——你若觉得「没区别」，说的就是这一层，没错 |
| **#2 Agent Skill（开放标准）** | `SKILL.md` 目录 + 渐进披露（agentskills.io 规范） | 一个**目录**（指令+脚本+资源）、**模型驱动**选择、能跑代码、**生产功能**、多厂通用 |
| **#3 harness 的 `Skill` 类** | 本仓库**曾经**有的那个 dataclass（`harness/skills/`，**已于 2026-06-21 删除**） | **纯文本 `content` + 关键词匹配**的最小类，无文件/无脚本/无模型驱动、**从未接进项目**，故移除 |

**一句话**：三者**理念相同（#1）**，但**实现/能力/标准/是否在用差一个量级（#3 ≪ #2）**。#3 不是「另一种 skill」，而是 #1 理念的一个「借了名字的 ~50 行教学影子」。

### 📛 本文统一用词（规范化）

为免歧义，本文（及 [harness-code-reading.md](./harness-code-reading.md) 第 6 站）统一这样称呼：

| 规范叫法 | 指什么 | 说明 |
|---|---|---|
| **Agent Skill** | #2 那个**开放标准/概念** | `SKILL.md` + 渐进披露。说「标准/概念」时一律用这个词 |
| **Claude Code Skill** | Agent Skill 在 **Claude Code 里的实现** | 是 Agent Skill 的一个**实例**（instance-of），非另一种东西。同理还有 Claude API skills、Cursor/Copilot/Google ADK 各自实现 |
| **harness 的 `Skill` 类** / **harness Skill 骨架** | #3 那个**本仓库的玩具类** | 永远带「harness」+「类/骨架」限定，**不简写成裸 `Skill`**，以免被当成概念 |
| **skill（泛称）** | 含糊的「能力」 | 仅口语；精确场景**不要**用，按上面三个之一说清 |

> 类比：**Agent Skill = USB 标准；Claude Code Skill = 某品牌按 USB 标准做的那个口；harness 的 `Skill` 类 = 自己用纸板仿做的一个"USB 模型"，插不进真设备。** 而「skill」只是"接口"这个泛称。
>
> 一个常见判断：**「我们通常说的 skill」≠ Agent Skill**——口语 skill 是泛指能力；只有特指 `SKILL.md` 那套时，才等于 Agent Skill。

### Agent Skill 的两条边界（易错点）

- **「标准」≠「实现」**——三层别混：

  ```
  Agent Skill（开放规范，agentskills.io）          ← 标准：只定义「SKILL.md 长什么样 + 怎么渐进加载」
    ├─ skills-ref                                  ← 官方「参考实现」
    └─ Claude Code / Claude API / Cursor / Google ADK …  ← 各「产品实现」
  ```
  Agent Skill 本身是**规范**；skills-ref 与各产品是**实现**。叫它「**开放标准/规范**」准确，**别叫「实现标准」**（会把标准和实现搅在一起）。

- **它只管「SKILL.md 这类」，不管「一切能力」**：Agent Skill 规范的是「把可复用能力**打包成 SKILL.md 单元 + 渐进披露**」这一种形态。工具（function calling）、RAG 也是「能力」，但**不是 Agent Skill**。所以——
  - ✅「Agent Skill 是 **SKILL.md 这类 skill** 的开放标准」
  - ❌「Agent Skill 是 **一切能力** 的标准」

- **是「事实标准」**：Anthropic 发起、开放、多厂采纳的 de-facto 主流，并非某机构强制的唯一标准。

**本文各节说的是哪一个**：§1–3 讲 **harness 的 `Skill` 类（#3）本身**及它与 Agent Skill 的对比；**§4–7 讨论的是要不要引入 Agent Skill（#2）**——即「自研 agent 要不要这种能力、何时、用哪个库」，**与 #3 那个玩具类无关**；§8 给两层各自结论。

---

## 1. harness 的 `Skill` 类是什么（#3）

> 🗑️ **已删除（2026-06-21）**：本节及 §2/§3 描述的 harness `Skill` 类**已整体移除并合并入 `master`**（OpenSpec change `remove-skills-skeleton`，PR #2）。以下为「它曾是什么、为何删」的**历史存档**——代码请查 git 历史，不要据此以为仓库里还有这个类。

- **（曾经的）定义**：一个 frozen dataclass —— `name` / `description` / `content` / `triggers`；`matches(task)` 用**确定性关键词子串匹配**判断相关；`SkillRegistry.load_for(task)` 返回命中的 skill。设计意图：把「可复用能力」声明成片段，**任务相关时才把 `content` 注入子 Agent 上下文**。
- **核心理念**：**渐进式披露 / 按需加载、不常驻**——别把所有能力说明永远塞进每个 Agent 的提示，用到哪类才加载哪类（对齐 Claude Code skills）。

## 2. 本项目现状（最重要的一条）

**现状：harness 里已没有任何 `Skill` 代码——骨架于 2026-06-21 整体移除并合并入 `master`（OpenSpec change `remove-skills-skeleton`，PR #2）。本项目从未、现在也不使用 skill。**

> 下面这段是**移除的依据存档**（「为何当初留、为何现在删」）：

- 删除前全仓库搜索，`Skill`/`SkillRegistry`/`load_for` 只出现在 `harness/skills/`（定义）、`tests/test_skills.py`（单测）、设计文档与学习笔记里——**运行路径一处都没调用**。
- 运行路径（`chat_handler` / `AgentLoop` / `SubAgent.run` / `delegate`）从未调用它；没有 `build_default_skill_registry`，也没有任何具体 Skill 实例。
- 它曾是 **Phase 7 故意留的扩展点骨架**，与第 3 站 `summary.py` 摘要 stub 同属「先搭骨架待后续 Phase 填」的套路；但生产化阶段判定该填的内容应走开放标准（见 §8），骨架本身零复用，故删。

## 3. harness 的 `Skill` 类 vs Agent Skill（以 Claude Code 实现为例）

理念相同（按需加载），实现深度差一个量级：

| 维度 | harness 的 `Skill` 类 | Agent Skill（Claude Code 实现） |
|---|---|---|
| 形态 | frozen dataclass，`content` 是一段提示文本 | 一个**目录**：`SKILL.md`（YAML frontmatter + Markdown 指令）+ 可捆绑脚本/资源 |
| 触发 | **确定性关键词子串匹配** | **模型自主判断**（读 description 决定） |
| 加载 | 一段字符串注入提示（设计意图） | **渐进式披露**：常驻 name+description；激活后载完整正文；按引用载脚本/资源 |
| 能力 | 仅纯文本提示片段 | 可含**可执行脚本、参考文档、多文件工作流** |
| 界面 | 内部 `load_for`，无独立工具 | 通过 **Skill 工具**调用 |
| 现状 | **已删除**（2026-06-21，PR #2）；曾仅有骨架+单测、未接入 | Claude 生产功能，真在用 |
| 取向 | 离线、确定、可单测（牺牲语义匹配/代码能力） | 在线、模型驱动、灵活 |

> harness 的 `Skill` 类 = Agent Skill 的「最小化、纯文本、关键词触发、可离线单测」的**教学影子版**。

## 4. 自研 agent 真的需要 skill 吗？

> 本节及 §5–7 的「skill」都指 **#2 通用 Agent Skill 能力**（要不要在自己 agent 里引入这种机制），不是 harness 那个玩具类 #3。

**多数情况不需要——包括本项目。** skill 不是基础件，而是「能力广度/可扩展性」到阈值才需要的缩放方案。

判据：一个新需求该用哪种原语——

| 新需求长这样 | 该用 |
|---|---|
| 一条事实/信息（价格、营业时间） | **RAG** |
| 一个确定性动作（下单、查档期、发短信） | **工具** |
| 一个领域的专才（预约 vs 咨询） | **子 Agent** |
| 全局行为/语气/边界 | **系统提示** |
| 每门店静态参数 | **配置/DB** |
| **「某情形该一步步怎么处理」的流程指令，且很多、要按情形按需加载、最好运营能自己改** | **← skill 的专属格** |

**skill 唯一不可替代点**：装**程序性指令（怎么做）** + 数量多到不能全塞进提示 + 需按情形动态加载。不同时满足这几条，用别的原语都更合适。

**结论**：本项目的需求已被 工具 + RAG（`search_knowledge` 端口，待接入独立 RAG 项目；本地 SQLite+FAISS 实现已于 2026-08-02 移除）+ 子 Agent + 系统提示 覆盖，skill 在这之上几乎不增量。

## 5. 本项目未来何时会用到 Agent Skill？

| 场景 | 是否真触发 | 判断 |
|---|---|---|
| **A. 运营 SOP/话术暴增**（改约/取消/退款/爽约/投诉/会员/促销/首到引导……每个都是多步流程） | ✅ **最可能** | 程序性指令 + 数量多 + 按情形加载 = skill 甜区。注意：「退款政策是什么」是 RAG；「执行退款流程」是 skill |
| B. 多门店 SaaS | ⚠️ 看情况 | 静态差异→配置/DB；只有「各店不同处理流程 + 按租户挂能力包」才轮到 skill |
| C. 让运营自助改助手行为 | ✅ 若是产品目标 | `SKILL.md` 人类可写，适合非开发维护流程 |
| D. 能力捆绑脚本/模板 | ⚠️ 多半是工具 | 确定性产物用工具更对 |
| E. 扩品类（美容/美甲…） | ✗ 主要是子 Agent | 跨领域共用的「怎么 upsell」才可能做 skill |

**触发信号**（出现即该上 skill）：子 Agent 的 `system_prompt` 越写越长、塞各种「如果遇到 X 就…」；改一条话术要改代码发版；不同情形流程互相打架、模型选错。

## 6. 要用的话，能复用现成方案吗？（选型）

**格式**：必复用 `SKILL.md` 开放标准（agentskills.io），别自己造。

**运行时/加载器**（对「自研 LangChain `bind_tools` 手写循环」的适配度）：

| 方案 | 能直接用于自研循环 | 代价/前提 |
|---|---|---|
| **`skills-ref`**（官方参考库，框架无关） | ✅ 最贴合 | 偏参考实现、较早；仍要写少量胶水接进 TAO 循环 |
| **LangChain Deep Agents**（`deepagents`+`langchain-skills`，`SkillsMiddleware`） | ❌ 仅在 `create_deep_agent()` 里 | 要迁到 Deep Agents/LangGraph；但本项目已是 LangChain 栈，迁移成本相对低、最省事 |
| Claude Agent SDK（`.claude/skills/` + `Skill` 工具） | ❌ 要重构到 SDK | 重新平台化 |
| Google ADK `SkillToolset` / 微软 Agent Framework | ❌ 要换框架 | 不适用 |
| Claude API skills（REST `/v1/skills` + `container`） | ⚠️ 调 API 挂参数 | 绑定 Claude API、beta |

**结论**：「只能纯手搓」已不成立；但「零改动适配你手写循环」的也没有。两条路——**留自研循环 → `skills-ref` + 薄胶水**；**可接受迁框架 → LangChain Deep Agents（开箱即用）**。

## 7. `skills-ref` 成熟度（实测 2026-06）

| 维度 | 数据 | 解读 |
|---|---|---|
| 标准/仓库热度 | `agentskills/agentskills`：⭐20,826、1,311 forks、36 贡献者 | 标准极火（但 stars 是**标准**热度，非库的生产成熟度） |
| 出身/许可 | Anthropic 发起、Apache-2.0 | 一线背书、许可友好 |
| 活跃度 | 建于 2025-12，最近推送 2026-05，未归档 | 在维护 |
| **库版本（PyPI `skills-ref`）** | **仅 0.1.0 / 0.1.1，2026-01-10 同日发布** | ⚠️ **pre-1.0、早期；之后 5 个月没发新版** |
| GitHub releases/tags | **无** | 无正式版本节奏 |
| 能力范围 | 校验 + 解析 + 生成提示目录 | ⚠️ **是「积木」非「整机」**——选择/注入编排仍要自己接 |

**结论**：**标准强、库还早。** 方向值得押；但 0.1.x、API 大概率会变，**生产关键路径现在别直接押**。

## 8. 一句话总结 / 决策

- **现在**：harness 里那个**关键词版 Skill 骨架（#3）已移除**（2026-06-21，PR #2 合并入 master；YAGNI，未接入、非生产级设计）；本项目用不上 skill。
- **它对未来生产版几乎零复用**：真要做生产级渐进披露 skill，需要 SKILL.md 格式解析、frontmatter 校验、三级披露、资源加载、模型驱动选择——这些 harness 类**一个都没有**，等于另起炉灶。所以**别「进化」这个关键词类**，那只是重写一遍 `skills-ref`/Deep Agents 已经做好的东西、还偏离开放标准。能从它继承的只有「理念理解」，不是代码。
- **将来**：真撞上「SOP/话术库膨胀 + 运营自助」→ 采用**开放 `SKILL.md` 标准 + 模型驱动加载**；按届时成熟度三选一：`skills-ref` 已 1.0 → `skills-ref`+薄胶水（留自研循环）；仍 0.x → pin+包 或 迁 **LangChain Deep Agents**（更 production-ready）；需求极小 → 照 SKILL.md 标准自写 ~百行 loader。**都不要复活关键词版。**
- **「以后也许用得到」≠ 需求**：先删，git 历史留底，真需要时按标准重做。

---

### Sources
- [Agent Skills 规范 + skills-ref](https://agentskills.io/specification) · [github.com/agentskills/agentskills](https://github.com/agentskills/agentskills) · [PyPI: skills-ref](https://pypi.org/project/skills-ref/)
- [LangChain Deep Agents — Skills](https://docs.langchain.com/oss/python/deepagents/skills) · [langchain-skills](https://github.com/langchain-ai/langchain-skills)
- [Claude Agent SDK — Skills](https://platform.claude.com/docs/en/agent-sdk/skills) · [Anthropic：Equipping agents with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- 本项目源码：~~harness/skills/~~（已于 OpenSpec change `remove-skills-skeleton` 移除，见 git 历史）· 现状结论见本文 §2
