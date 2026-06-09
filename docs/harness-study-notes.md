# Agent Harness 学习笔记

> 📍 本文属于 harness 学习系列（**第 1 步 · 概念入门**）。总览见 [harness-index.md](./harness-index.md)。
>
> 整理自一次关于 harness 的深入问答。配套文档：
> - [harness-engineering-official-notes.md](./harness-engineering-official-notes.md) — OpenAI / Anthropic 两份官方 harness 工程手册精读
> - [harness-refactor-plan.md](./harness-refactor-plan.md) — 本项目从 workflow 到 harness 的重构计划
>
> 关键词：Agent Harness、TAO/ReAct loop、context engineering、ECC、vibecoding。

---

## 📖 怎么读这份笔记

**这份笔记是给谁的**：刚接触 "agent harness" 这个概念、想搞清楚它到底是什么、以及要不要给自己的项目/工具装一堆增强包的人。

**全文分三部分，可以按需读**：

| 部分 | 章节 | 解决什么问题 |
|------|------|-------------|
| 🟢 **概念入门** | 第 1–3 章 | harness 是什么？它长什么样？为什么一个词有这么多意思？ |
| 🟡 **方法论** | 第 4–5 章 | 怎么判断我的项目是不是 harness？怎么衡量它好不好？ |
| 🔴 **实战决策** | 第 6–8 章 | 要不要装 ECC 这类增强包？该怎么边学边重构？ |

**如果你只有 5 分钟**，读这三句话就够了：

1. **Harness = 套在 LLM 外面的那一整套"非模型"基础设施**——模型负责"想"，harness 负责把"想"变成可靠的"做"。
2. **同一个模型，配不同的 harness，干活质量天差地别**——所以行业共识是"投资你的 harness，而不是只换你的模型"。
3. **好的 harness 不是"装出来的"，是"长出来的"**——与其整包安装别人的增强层，不如边做边沉淀自己的那一层。

> 💡 第 3.2 节的"马挽具"比喻是理解整个概念的钥匙。如果读到后面觉得抽象，回去看那一节。

---

## 1. 什么是 Agent Harness

> **一句话**：Harness = 包裹在 LLM 推理循环外面的那一整套"非模型"基础设施。
> 模型负责**推理（reasoning）**，harness 负责**能力（capability）**。

它的作用是：把模型的"思考"变成可靠的"行动"。

### 它是怎么运转的：TAO / ReAct 循环

harness 的核心是一个不断转的圈，叫 **TAO 循环**（也叫 ReAct 循环）。TAO = Thought（想）→ Action（做）→ Observation（看结果）：

```
组装上下文 → 调 LLM → 解析输出(tool_calls) → 执行工具 → 把结果喂回 → 重复，直到完成
   （想）      （想）        （想要做什么）       （做）        （看结果）
```

> 通俗讲：模型先想"我该干嘛" → 决定调用某个工具 → harness 真的去执行 → 把执行结果再塞回给模型 → 模型看着结果想下一步……如此循环到任务完成。

**一个细节**：现代 harness 用 **native tool calling**（原生工具调用）——模型直接返回结构化的 `tool_calls` 对象（机器能直接读的格式），而不是吐一段自由文本再让人写代码去解析。这更可靠。

### 2026 年的行业共识

- 「如果 2025 是 **Agent 之年**，2026 就是 **Harness 之年**。」
- 「**投资你的 harness，而不是只换你的模型。**」
- 一个数据：**65% 的企业级 AI 失败源于 harness 缺陷**，而不是模型不行。具体是三类毛病（记住这三个名字，后面反复用到）：
  - **上下文漂移（Context Drift）**——喂给模型的信息越来越偏、越来越脏。
  - **schema 错位（Schema Misalignment）**——工具的输入/输出格式对不上。
  - **状态退化（State Degradation）**——跨步骤/跨会话的记忆丢失或变味。

---

## 2. 一个完整 Harness 的组成

> **一句话**：一个完整的 harness 大致由 7 个组件拼成，**Claude Code 就是教科书级的实现**。

下面用 **OpenClaw 七组件**当框架来看（OpenClaw 是一个开源 agent 项目）：

| 组件 | 大白话 |
|------|------|
| Channel / Gateway | **接入层**——请求从哪进来、会话怎么分发 |
| Agent Runtime | **核心大脑**——agent loop + 工具调度 + 上下文管理 |
| Plug-ins & Skills System | **可复用能力**——按需加载的技能包 |
| Memory & Knowledge System | **记忆**——短期/长期记忆、知识检索 |
| LLM Provider | **模型接口**——把"接哪个模型"抽象出来 |
| Local Execution | **干活的手**——工具真正执行的地方（shell/文件/API） |
| Guardrails / Observability | **护栏 + 仪表盘**——权限/超时/重试，加上日志、追踪、评估 |

OpenClaw 的循环本质就一句话：「**观察 → 用工具 → 检查结果 → 决定下一步**」。这个闭环一旦建立，系统就能自己持续推进任务——这正是第 1 章那个 TAO 循环。

---

## 3. 关键澄清：三个不同层次的"Harness"

> **一句话**：「harness」这个词在不同语境下指三样**完全不同**的东西，这是新手最容易绕晕的地方，务必分清。

| 叫法 | 是什么 | 例子 |
|------|--------|------|
| ① **运行时 harness** | 嵌进**你自己 app** 里的 agent loop | 你重构后的预约系统大脑 |
| ② **编码 harness / vibecoding 工具** | 帮你**写代码**的 agent 工具 | Claude Code、Cursor、Codex、OpenCode |
| ③ **Harness 增强层 / operator system** | 装在 ② **之上**的能力包 | ECC |

对照着记：

- 「用 harness 做 vibecoding」 → 指 **②**，你现在用的 Claude Code 就是。
- 「把我的项目改成 harness」 → 指 **①**，你要亲手建的那个。
- ECC → 是 **③**，它不是 harness 本身，而是 ② 的插件包。

> 💡 后面第 6–7 章评估的 ECC，争论的全是"要不要给 ② 装上 ③"。心里清楚这一点，那两章就好读了。

---

### 3.1 Harness 的家族全景（跨领域）

> **一句话**：「harness」远不止 agent 圈在用，从软件测试到 ML 评估都有它，但有**一条共同主线**。

那条主线是：

> **harness = 包裹某个"核心"的脚手架：给核心喂输入、驱动它运行、观察输出、施加约束——而核心本身是可替换的。**

按年代排，这个词在技术圈的几个家族：

| 家族 | 叫法 | 包裹的"核心" | 例子 | 年代 |
|------|------|-----------|------|------|
| 软件工程（最老） | **Test harness**（测试） | 被测代码 | JUnit、pytest | 传统软工 |
| ML/LLM 评估 | **Eval harness**（评估） | 被测模型 | `lm-evaluation-harness`、HELM | LLM 时代 |
| Agent 评估 | **Benchmark harness**（基准） | 被测 Agent | SWE-bench harness | Agent 时代 |
| Agent 运行时（2026 最热） | **Agent / Runtime harness** | 做推理的 LLM | Claude Code、OpenClaw | 2026 |

> 上表最后一行的"Agent 运行时 harness"，内部又细分为第 3 节的 ①②③ 三个子层。

**一个高频混淆点：Eval harness ≠ Agent harness**

- **Eval harness** 是"**测量**用"的脚手架——把对象关进标准环境里打分。
- **Agent harness** 是"**运行**用"的脚手架——在真实任务里持续行动。
- 二者会交汇：要评估一个 agent harness 好不好，就得用 benchmark harness 去测它。
- 一个关键认知：**同一个模型，套在不同 harness 下跑 SWE-bench，分数能差很多**——这就是"投资 harness 而非模型"的硬证据。

**和本项目的连接**：这次重构会同时碰到三种 harness——

- **Test harness**：`tests/` + pytest（已有）
- **Eval harness**：Phase 0 要建的评估集（测量重构前后质量）
- **Agent harness**：Phase 1–7 要建的运行时（重构目标）

---

### 3.2 为什么一个词能有这么多含义：词源与演变

> **一句话**：所有这些 harness 的意思，都来自同一个古老比喻——**套在马身上的挽具**。理解了这个比喻，前面所有定义就都"通"了。

#### 核心比喻：套在"马"身上的挽具

- **词源**：约 **1300 年**，源自古法语 **harnois**（武器、装备、马具、家什），可能更早来自古诺尔斯语 *hernest*（"军队的给养"：herr 军队 + nest 给养）。最初指**盔甲 / 战马的装备**。
- **14 世纪初**：转指**役畜的挽具**（马的缰绳、套具）。
- **1690 年代**：动词出现引申义——「**驾驭某种力量为我所用**」(harness the wind / steam / energy)。

**关键就在这里**——马挽具的功能形态是：

> 一套**附着在强大但桀骜的核心（马）之上**的装备，**控制它、引导它、约束它**，把它的**原始力量转化为有用的、定向的、安全的功**，同时**让操作者始终掌控**。

#### 为什么这个比喻能迁移到这么多技术领域

因为前面那些技术造物，**共享完全相同的功能形态**。一张表看懂：

| 共同特征 | 马挽具 | 测试 harness | Agent harness |
|----------|--------|--------------|---------------|
| 是"配套装备"，非核心本身 | 缰绳套具 | 测试脚手架 | loop+工具+护栏 |
| 附着于一个强大/能动的核心 | 马 | 被测代码 | LLM |
| 控制、引导、约束 | 驾驭马 | 驱动并断言 | 调度工具、护栏 |
| 原始力 → 有用定向输出 | 拉车 | 验证结果 | 完成任务 |
| 操作者始终掌控 | 车夫 | 开发者 | 用户/权限 |
| 核心可替换 | 换匹马 | 换段代码 | 换个模型 |

> 正因为功能形态不变，这个隐喻就能干净地平移到任何"**需要驾驭一个强大核心**"的场景。

#### 工程领域的演变链

```
战甲/马具(1300) ──"驾驭力量"引申(1690s)──┐
                                          ├─► 工业时代：
                                          │     Wiring/Cable harness（线束：捆扎、布线、控制信号与电流）
                                          │     Safety harness（安全带：固定、约束人体）
                                          │
late 20C 软件 ──► Test harness（驱动并观察被测代码；近亲：test bench/rig/fixture）
                          │
ML 时代 ──────► Eval / Benchmark harness（标准化地驱动模型/Agent 并度量）
                          │
2026 Agent ──► Agent / Runtime harness（LLM 就是那匹"马"：原始能力极强，
                必须被"驾驭"——控制、引导、保安全——才能干有用的活）
```

> **一个回响**：2026 的"agent harness"几乎是 1690 年代那个引申义的字面回归——"harness the power of the model"（驾驭模型的力量）。三百年后，我们还是在用同一个比喻：给一个强大的核心套上挽具，让它为我所用。

#### 顺带辨析：harness 在一堆近义词中的位置

`harness` / `rig` / `bench` / `fixture` / `scaffold` / `framework` 常被混用，但语感不同：

- **fixture**：固定的环境/数据（被动）
- **framework**：你在其中编写代码的更宽结构
- **harness**：**主动驱动并控制那个"活"的核心**——这正是它区别于其他词的语感，也是为什么 agent 圈选它而不是 "framework"。

---

## 4. Workflow vs Harness（本项目的诊断）

> **一句话**：当前预约项目的 `agents/` 层其实是**硬编码工作流（workflow）**，还不是真正的 harness——区别在于"谁来决定流程"。

| 维度 | Workflow（现状） | Harness（目标） |
|------|------------------|-----------------|
| 编排 | `if category=="appointment"` 一次性路由 | TAO 循环，模型自主决策 |
| 工具 | LLM 吐字符串，人工 `if` 匹配 | native tool calling |
| 流程决定权 | **开发者写死**，需预判所有分支 | **模型在 loop 里自己决定** |
| 能力 | 只能处理预设组合 | 能处理"约不到就换人再约"等未预设组合 |

**这就是 Agent 的价值所在**：模型能处理你没写死的情况。

> 简单分辨法：如果流程的每一个岔路口都是你用 `if/else` 写死的 → 那是 workflow；如果是模型在循环里自己看情况决定下一步 → 那才是 harness。

---

## 5. 如何衡量"Harness 质量"

> **一句话**：harness 好不好，看 5 个杠杆；要快速估算，记住一个心智公式。

### vibecoding 时，harness 质量由 5 个杠杆决定

| 杠杆 | 含义 | 谁决定 |
|------|------|--------|
| **L1 模型能力** | 推理/写码本身强弱 | 模型 |
| **L2 上下文质量** | 喂给模型信息的**信噪比** | 上下文里装了什么 |
| **L3 反馈/验证回路** | 改完能否自动检验、纠错 | 测试/review/hooks |
| **L4 状态持久化** | 跨会话记忆不丢、不漂 | 记忆机制 |
| **L5 人的操舵** | 需求拆解与判断 | 你 |

### 一个好用的心智公式

```
harness 质量 ≈ (信噪比 × 验证回路) ÷ 故障面
```

- **提升分子**：高信号上下文（L2）+ 强验证回路（L3）。
- **控制分母**：少装那些会自动执行、增加故障面的东西。

> 💡 这个公式是下一章评估 ECC 的标尺：任何增强包，都要问它对"信噪比、验证回路、故障面"各做了什么。

---

## 6. ECC 案例分析（一次客观评估的范例）

> **一句话**：ECC 是个第三方增强包（前面说的 ③），它确实拉动了一些真实杠杆，但"装了就更好"在"学习+重构本项目"这个场景下**站不住脚**。

### ECC 是什么

- 一个 「**harness-native operator system**」，跨 Claude Code / Cursor / Codex 提供统一的能力包。
- 自述包含：63 子 Agent、251 skill、29+ rules、8+ hooks、MCP 配置、AgentShield 安全扫描（102+ 规则）。
- **本质是 ③（增强层），不是 harness 本身。**

### 它确实拉动了真实的 harness 质量杠杆

对应 2026 的三大失败模式（就是第 1 章那三个）：

| 失败模式 | ECC 的机制 | 有效性 |
|----------|-----------|--------|
| 上下文漂移 / 状态退化 | SessionStart 载入 + Stop 保存会话状态 | ✅ 真持久化 |
| 输出质量不稳 | always-on rules + PostToolUse 检查 | ✅ 加了验证层 |
| 安全风险 | AgentShield 静态扫描 | ✅ 多道安全网 |
| 单 Agent 上下文膨胀 | 任务分流给专用子 Agent | ✅ 聚焦上下文 |

### 但"装了更稳"不成立——它是把双刃剑

1. **更多自动执行的机器 = 更大故障面**（一个坏 hook 就能搞崩整个会话）。
2. **251 skill / 29 rule，多 ≠ 好**：它们会互相冲突、抢上下文、选错子 Agent，本身就在制造 schema 错位。
3. **上下文开销**：每次 SessionStart 都载入历史，长会话拖慢、占 token。
4. **未经审计**：star 多 ≠ 在你机器上可信；它影响全局 `~/.claude`，波及你所有项目。

### 方法论结论（针对"学习 + 重构本项目"场景）

用第 5 章的杠杆逐项打分：

- **L2 上下文**：**净负**——多语言/框架包/MCP 大多无关，稀释信噪比；always-on rule 还会抢方向盘。
- **L3 验证回路**：**微正，但可被原生替代**——`/code-review`、`/verify`、pytest、评估集更可控。
- **L4 状态持久化**：**微正，但场景用不上**——git + 计划文档 + 项目记忆已经承载了。
- **故障面**：**净负**。
- **➡️ 净效应：中性偏负。"装了会更好"举证不成立。**

### 客观性补充：什么情况下结论会反转

ECC 在以下画像下会变成正向选择——

- 多语言、大型、多人的生产代码库；
- 团队需要统一强制规范；
- 有人审计并裁剪过；
- 目标是交付效率而非学习。

---

## 7. 最终决策：装不装 ECC

> **一句话**：**不（整包）装**。用 Claude Code 原生 + 内置 skill，把可复用实践沉淀进你自己的 `~/.claude`。

### 即便目标是"生产级 + 未来更多项目"，结论依然成立，但理由要升级：

1. **生产级 ≠ 装一个好用的开发工具包**
   - "生产级"是你 **app 运行时 harness（①）** 的属性（来自 Phase 5/6/7 的护栏/可观测/隔离），不是开发工具的插件决定的。
   - 越要做生产级，**越该提高**对"装什么进全局环境"的审查标准，而不是降低。

2. **多项目复用 → 指向"你自己的层"，而不是 ECC**
   - 最高价值的资产是：**你边做边沉淀的、完全理解的、贴合你技术栈（Python/FastAPI）的 `~/.claude` 层**。
   - 理由：每一块你都理解（能修能调）、贴合栈（无噪音）、可信（不是来路不明的自动执行代码），而且**沉淀过程本身就是在练 harness 方法**。
   - ECC 的正确角色：**当"选品参考"——审计之后 cherry-pick 个别组件**，而非整包安装。

### 可执行的决策规则

| 情形 | 做法 |
|------|------|
| 现在（学习 + 重构本项目） | 不装。原生 + 内置 skill，把可复用实践沉淀进自己的 `~/.claude` |
| 做完 1–2 个项目后反复手搓同样的东西 | 审计 ECC，cherry-pick 验证过的组件；要整包就用 `minimal`（无自动 hooks） |
| 公司 / 生产项目 | 任何第三方全局 hooks 先过安全审查，默认不装 |

> **核心洞察**：你要的不是"装一个现成的好 harness 层"，而是"**长出一个属于你的好 harness 层**"。而长出它的最好方式，就是动手重构——重构过程会告诉你一个好 harness 层到底需要什么。

---

## 8. Vibecoding 重构的正确姿势（兼顾学习）

> **一句话**：纯 vibecoding（只说需求、不看代码）会把你本该学到的东西外包掉。用"**理解型 vibecoding**"来兼顾速度和学习。

四条原则：

1. **按 Phase 走，小步 git 提交**：每个 Phase 单独开分支，改完跑评估集再合。
2. **每次改动先讲清"为什么这么改"再落地**：既享受速度，又真学到东西，还能防跑偏。
3. **测试/评估兜底**：Phase 0 先把评估网建好，之后每一步都对照它防回归。
4. **关键代码亲手敲一遍**：比如 Phase 3 的 agent loop，亲手写理解最深。

---

## 9. 术语速查

| 术语 | 含义 |
|------|------|
| **Harness** | 包裹 LLM 的非模型运行时基础设施 |
| **TAO / ReAct loop** | Thought→Action→Observation 的工具调用循环 |
| **Native tool calling** | 模型直接返回结构化 tool_calls（机器可读，无需人工解析） |
| **Context engineering** | 每一步精选最小、最高信号的 token 集 |
| **Guardrails** | 权限/超时/重试/校验等护栏 |
| **Sub-agent** | 主 Agent 派生出的专用子 Agent |
| **Skill** | 可复用、按需加载的工作流定义 |
| **Context Drift / Schema Misalignment / State Degradation** | 三大 harness 失败模式（上下文漂移 / schema 错位 / 状态退化） |

---

## 参考来源

- Agent Harness Engineering — The Rise of the AI Control Plane (Adnan Masood)
- The Anatomy of an Agent Harness (Avi Chawla)
- awesome-harness-engineering (GitHub)
- Microsoft Agent Framework at BUILD 2026
- OpenClaw: Anatomy of a viral open source AI agent (All Things Open)
- What Is an AI Agent Harness? How OpenClaw Works as an Agent Runtime
- Anthropic context engineering guide
