# 两份官方 Harness 工程手册 · 精读笔记

> 📍 本文属于 harness 学习系列（**第 2 步 · 官方手册**）。总览见 [harness-index.md](./harness-index.md)。
>
> 精读 OpenAI 与 Anthropic 两篇 harness 工程文章的学习笔记。配套：[harness-study-notes.md](./harness-study-notes.md)（概念入门）、[harness-refactor-plan.md](./harness-refactor-plan.md)（本项目重构计划）。
>
> **原文**：
> - OpenAI — [Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/)
> - Anthropic — [Harness Design for Long-Running Application Development](https://www.anthropic.com/engineering/harness-design-long-running-apps)
>
> ⚠️ **来源说明**：OpenAI 原文页面抓取时返回 403，本笔记中 OpenAI 部分的细节由多个可靠二手来源（InfoQ、Milvus、ZBuild 等）交叉验证整理；待原文可访问时建议复核。Anthropic 部分基于原文全文。

---

## 📖 怎么读这份笔记

**这份笔记回答一个核心问题**：同样的 AI 编码工具，为什么高手能产出可靠代码、新手却不能？两家公司的答案惊人一致——**差距不在模型，在你给它搭的"环境"**。

| 部分 | 章节 | 一句话 |
|------|------|--------|
| 🅰️ **OpenAI 篇** | 第 1 章 | 把整个工程环境"机械化"地搭在 agent 周围，人退到"设计环境"的位置 |
| 🅱️ **Anthropic 篇** | 第 2 章 | 长跑型 agent 怎么管上下文、怎么把"生成"和"评估"分开 |
| 🔀 **合读对比** | 第 3 章 | 两篇的共识、分歧、互补 |
| 🎯 **落地** | 第 4 章 | 映射到我们的 5 杠杆 + 各 Phase + 可执行清单 |

**如果你只有 3 分钟**，记住两家共同的三句话：

1. **「The agent is not the hard part — the harness is.」**（难的不是 agent，是 harness。——OpenAI）
2. **「每一个组件，都编码了一个'模型自己做不到'的假设。」**（所以模型变强了，就该拆组件。——Anthropic）
3. **成功 = 高信号上下文 + 机械化验证 + 把生成和评估分开**——这是两篇唯一都强调的三件事。

---

## 🧭 一句话定位：这两篇分别教你什么

> 这两篇**不是同一个用途**，正好一篇一个方向。判断标准看「**这套 harness 部署在哪**」：

| 文章 | 教你哪件事 | harness 住在哪 | 对应「三层」 |
|------|-----------|---------------|-------------|
| **OpenAI 篇** | 🅰️ **当好"用 agent 的人"**——怎么用 coding agent 把代码写好 | 你的**代码仓库里**（AGENTS.md、黄金准则、CI） | 围绕 ② 搭的环境 |
| **Anthropic 篇** | 🅱️ **当好"造 agent 的人"**——怎么设计 agent 让它长跑更稳 | agent 的**运行时里**（loop、上下文重置、角色分离） | 造 ①（运行时 harness） |

（「三层 ①②③」见 [概念笔记第 3 章](./harness-study-notes.md)。）

**判断口诀**：harness 住在**代码仓库里** = 教你用 agent（开发期）；harness 住在 **agent 大脑里** = 教你造 agent（运行期）。

**对本项目的关键推论**：

- **Anthropic 的经验能直接迁到你的预约 agent**——它的教训（上下文管理、生成/评估分离、复杂度匹配能力）是**领域无关**的，换成"预约 agent 怎么处理多轮预约"照样成立 → 直接喂给 Phase 3。
- **OpenAI 的招大多绑在"代码"上**——黄金准则、CI 校验的是代码，帮你**用 Claude Code 把系统重构出来**（开发期），但**不进入预约 agent 的运行时**。一句话：OpenAI 帮你盖房子，但不住进房子里。

**所以你要戴两顶帽子**：

- 敲键盘让 Claude Code 改代码时 → 你是 **OpenAI 篇**的读者。
- 设计"预约 agent 内部怎么转"时 → 你是 **Anthropic 篇**的读者。

> 底层内功是相通的（精上下文、分离评估、客观验证、别过度设计），但**用途分两个方向**——这正是 [第 5 章](#-第-5-章--两本操作手册提炼版) 两本操作手册的由来。

---

# 🅰️ 第 1 章 · OpenAI：Harness Engineering

> **一句话**：OpenAI 把"写软件"重新定义成"**设计让 agent 自主写软件的环境**"。人不写代码，人写**规则、文档、约束、验证**，并让它们**被机器强制执行**。

### 1.0 它的定义

> **Harness engineering = 设计自主 agent 周围的执行环境**：它能调用哪些**工具**、从哪里拿**信息**、如何**自我验证**决策、以及**何时停止**。

最震撼的一句话：

> **「The agent is not the hard part — the harness is.」**
> 成功取决于环境质量，而不只是模型能力。

### 1.1 标志性实验：5 个月，百万行，零手写代码

| 指标 | 数据 |
|------|------|
| 周期 | 5 个月 |
| 团队 | 从 3 人 → 7 人 |
| 产出 | ~**100 万行**生产代码 |
| PR 数 | ~**1,500 个** merge |
| 提速 | 约为手写的 **1/10 时间** |
| 手写源码 | **0 行**（初始脚手架由 GPT-5 生成） |

人只做四件事：**给 prompt、给反馈、过 PR、过 CI**。这证明了——环境搭对了，agent 能在"几百个决策"的长链条上可靠运行。

### 1.2 核心实践（六板斧）

#### ① AGENTS.md：从"规则书"改成"地图"

这是最值得学的一个**失败→成功**的故事：

| 阶段 | 做法 | 结果 |
|------|------|------|
| ❌ 初版 | 一个大文件，塞进所有约定/规则 | 失败：挤占上下文、扁平结构让一切显得同等重要、规则几周就过期、无机械校验 |
| ✅ 改版 | 压缩到约 **100 行**，当**导航地图**用，指向结构化的 `docs/` 目录 | 成功：agent 按需去取精确信息 |

`docs/` 里放：设计决策、执行计划、产品规格、参考文档。

> **底层原则（牢记）**：**「if something isn't in context at runtime, it doesn't exist for the agent.」**（运行时不在上下文里的东西，对 agent 就等于不存在。）

#### ② Golden Principles（黄金准则）

把"有主见、可机械执行"的规则**写进仓库**：

1. **优先用共享工具包**，而非手搓 helper（集中管理不变量）
2. **在数据边界做校验**（类型安全），而非无保护地乱探
3. **一个概念一个文件**（让 agent 容易发现）
4. **显式优于隐式**（消灭"只可意会"的部落知识）

#### ③ 机械化强制（关键中的关键）

规则不靠 agent 自觉，靠工具兜底：

- **Linter 规则** + **结构测试** + **CI 闸门** → **自动拒绝**违规 PR
- 自定义 linter 的报错信息里**内嵌修复指令**——防止 agent 照抄仓库里（包括有问题的）旧模式
- **agent 走和人类开发者完全相同的校验流水线**

#### ④ 架构边界：单向依赖分层

```
Types → Config → Repo → Service → Runtime → UI
```

依赖**只能单向流动**：UI 可以依赖 Runtime/Service，但 **Service 永远不准 import UI**。用结构测试机械校验，防止架构漂移。

#### ⑤ Repository-First：知识全部沉淀进仓库

所有开发知识都必须是**仓库里的产物（artifact）**：markdown 文档（ARCHITECTURE.md、约定、onboarding）、schema/类型定义、带验收标准的可执行任务计划、配置与 lint 标准。

> 原则：**「anything it cannot access in-context while running effectively does not exist.」**

**Executable Plans（可执行计划）**的结构：目标与范围 → 明确的改动文件清单 → 依赖声明 → 要遵守的架构约束 → 可测试的验收标准。这些都**版本化**，**人先审再执行**。

#### ⑥ 自动垃圾回收 / 后台重构

一个**持续运行的后台系统**对抗代码漂移：

- 扫全库，找出偏离黄金准则的地方
- 更新每个模块的**质量评分**
- 自动提**针对性重构 PR**——大多数**一分钟内**被 merge

> 它取代了过去**吃掉约 20% 工程时间**的手动清理。这是"持续小步改进"取代"周期性还技术债"。

### 1.3 工具与验证

- 集成 **Chrome DevTools Protocol**：截图、观察运行时事件、查日志
- 设**客观性能阈值**（例：服务必须 **800ms 内**启动）
- 后台用 **LogQL / PromQL** 持续监控
- agent 能跑 **6+ 小时**的长任务并持续验证
- Codex **直接用标准开发工具**（`gh`、本地脚本、仓库内嵌 skill）拿上下文，不需要人复制粘贴

### 1.4 OpenAI 篇 · 一页速记

> 把工程做成**机器可读的脚手架**：精简地图（AGENTS.md）+ 黄金准则 + linter/CI 机械强制 + 单向架构 + 仓库即真相 + 后台自动重构。人的角色从"写代码"升维到"**设计环境、声明意图、给结构化反馈**"。

---

# 🅱️ 第 2 章 · Anthropic：长跑型 App 的 Harness 设计

> **一句话**：当任务要跑很久（long-running），harness 设计**直接决定成败**。重点是怎么**管上下文**、怎么把**生成与评估分开**、以及**harness 复杂度要随模型变强而精简**。

开篇定调：

> **「Harness design has a substantial impact on the effectiveness of long running agentic coding.」**

### 2.1 上下文管理：用 reset，别用 compaction

两个长跑崩坏点：

1. **上下文退化**：窗口被填满时模型失去连贯。
2. **Context anxiety（上下文焦虑）**：模型快到极限时会**草草收尾**、提前"交差"。

**对策**——

| 方案 | 做法 | 评价 |
|------|------|------|
| Compaction（压缩） | 原地把早期对话总结掉 | 次选 |
| ✅ **Context reset（重置）** | **清空窗口** + **结构化交接**，状态靠产出物（文件）传递 | 首选：给 agent 一块"干净白板" |

### 2.2 把"生成"和"评估"分开（GAN 式三 agent）

> **关键洞察**：agent 会**过度夸奖自己的工作**，主观任务尤甚。自评不可靠 → 必须有**外部反馈回路**。

灵感来自 GAN（生成对抗网络），拆成三个角色：

| 角色 | 职责 | 要点 |
|------|------|------|
| **Planner（规划）** | 把简短 prompt 扩展成完整产品规格 | **刻意保持高层**，避免错误层层放大；前置注入设计原则 |
| **Generator（生成）** | 实现功能 | 早期用 sprint 拆分（后随模型变强简化） |
| **Evaluator（评估）** | 验收 | 用 **Playwright 像真实用户一样操作**跑起来的 app，按**具体标准**测过才放行 |

- agent 之间**通过文件通信**，形成显式交接点。
- 动手前 Generator 与 Evaluator 先谈好 **"sprint 契约"**：定义成功标准 + 可测行为——把抽象规格和具体实现接上。

### 2.3 主观任务也要"可打分"

前端设计这种主观领域，定 4 条可评分标准：

| 标准 | 含义 |
|------|------|
| **Design Quality** | 视觉一致性（色彩、排版、布局、图像） |
| **Originality** | 有刻意的创意选择，而非套模板 |
| **Craft** | 技术执行（层级、间距、和谐、对比） |
| **Functionality** | 用户能否完成任务、界面是否清晰 |

> **刻意给 Design + Originality 加权**，把模型推离 **"generic AI slop"**（千篇一律的 AI 垃圾感）。
>
> 更妙的发现：prompt 里加一句 **"museum quality designs"** 就能显著改变产出——**精心校准的标准本身就在操舵模型**，甚至在评估反馈开始之前就生效了。

### 2.4 黄金法则：harness 复杂度要匹配模型能力

> **「Every component encodes an assumption about what the model can't do on its own.」**
> 每一个组件，都编码了一个"模型自己做不到"的假设。

推论：**模型变强了，就该回去拆组件**。当 Opus 4.6 在规划、长上下文检索、自我纠错上显著变强后，他们**主动移除承重组件**：

- 去掉僵硬的 sprint 拆分
- 评估从"每个 sprint 一次"降到"整体构建结束时一次"（任务难度允许时）
- **但保留 Planner**——因为单 agent 生成仍会**漏掉功能范围（under-scope）**

### 2.5 成本/质量的硬数据

| 方案 | 耗时 | 成本 | 结果 |
|------|------|------|------|
| 单 agent 裸跑 | 20 分钟 | **$9** | 功能被偷工、缺核心能力 |
| 完整多 agent harness | 6 小时 | **$200** | **真的能跑、功能完整** |

**20 倍成本**换来"从不能用到能用"——这是 harness 价值最直白的量化。

### 2.6 Evaluator 的调教

评估 agent 一开始会"**找到真问题、又自己把它合理化掉**"。通过反复按失败案例打磨 prompt，最终做到：

- 测**边界情况**，而非表面验证
- 校验 **UI/API 集成**和**数据库状态**一致性
- 产出**具体、可执行**的 bug 报告，**带代码位置**

### 2.7 仍存在的局限（诚实的一面）

即便有精巧 harness，模型仍会：不直觉的用户流程（漏掉隐含的任务次序）、深层嵌套功能里**偷偷 stub**、错过布局打磨机会。

> 结论：**harness 在"任务复杂度逼近模型可靠上限"的前沿地带最有价值。**

### 2.8 Anthropic 篇 · 一页速记

> 长跑靠四招：**context reset 保持白板** + **生成/评估分离**（GAN 式 Planner/Generator/Evaluator + 文件通信 + sprint 契约）+ **主观任务可打分**（加权原创性、校准措辞）+ **复杂度随模型能力增减**。

---

# 🔀 第 3 章 · 两篇合读

### 3.1 共识（两家都强调的）

| 共识 | OpenAI 的说法 | Anthropic 的说法 |
|------|--------------|-----------------|
| **难点在 harness，不在模型** | 「The agent is not the hard part — the harness is」 | 「harness design has a substantial impact」 |
| **上下文要精、要按需** | AGENTS.md 当地图，运行时不在=不存在 | context reset，给干净白板 |
| **生成 ≠ 评估，要外部验证** | linter/CI/结构测试机械强制 | 独立 Evaluator + 客观标准 |
| **客观、可测的验收标准** | 800ms 启动阈值、CI 闸门 | 4 条可评分设计标准 |
| **人退到"设计环境"的位置** | 写规则/文档/约束，给反馈 | 写规格、调校 prompt 与标准 |

### 3.2 侧重点不同（互补）

| 维度 | OpenAI 偏重 | Anthropic 偏重 |
|------|-------------|----------------|
| 场景 | **大团队、长期演进**的代码库（百万行） | **单次长跑任务**（从 0 造一个 app） |
| 解决漂移 | 后台**自动重构** + 黄金准则 + 单向架构 | **context reset** + 文件交接 |
| 验证手段 | linter / 结构测试 / CI（**静态 + 流程**） | Playwright 跑真 app（**动态 + 行为**） |
| 演进观 | 把规则**沉淀进仓库**长期复利 | 模型变强就**拆掉**多余组件 |

> **怎么用**：OpenAI 教你"**把可复用的工程纪律机械化、沉淀进仓库**"；Anthropic 教你"**单个长任务里怎么排兵布阵、且别过度设计**"。前者管"长期"，后者管"单次"。

### 3.3 一个统一心智模型

```
       ┌─────────────── 你（设计环境的人）───────────────┐
       │  写：意图/规格、规则、文档地图、验收标准         │
       ▼                                                  │
   ┌────────┐  喂高信号上下文   ┌──────────┐  机械验证    │
   │ Harness │ ───────────────► │   LLM    │ ──────────► 反馈回到 Harness
   │（环境）  │ ◄─────────────── │ （那匹马）│              │
   └────────┘   工具结果         └──────────┘              │
       │                                                   │
       └──── 不在上下文 = 不存在；复杂度匹配模型能力 ──────┘
```

---

# 🎯 第 4 章 · 落地到我们的项目

### 4.1 映射到笔记里的 5 杠杆

（5 杠杆见 [harness-study-notes.md 第 5 章](./harness-study-notes.md)）

| 杠杆 | OpenAI 给的手法 | Anthropic 给的手法 |
|------|----------------|--------------------|
| **L2 上下文质量** | 精简 AGENTS.md 当地图 + docs/ 分层 | context reset，干净白板 |
| **L3 验证回路** | linter/结构测试/CI 机械强制 | 独立 Evaluator + Playwright + 客观标准 |
| **L4 状态持久化** | repository-first，知识全沉淀进仓库 | 文件交接 + sprint 契约 |
| **L5 人的操舵** | 声明式意图 + 可执行计划（人先审） | 写规格、校准 prompt 措辞与评分标准 |

### 4.2 映射到重构 Phase

| Phase | 可直接照搬的官方做法 |
|-------|---------------------|
| **Phase 0（评估网）** | Anthropic 的"生成/评估分离" + 客观可评分标准；OpenAI 的 CI 闸门 |
| **Phase 3（agent loop）** | Anthropic 的 context reset、Planner/Generator/Evaluator 结构 |
| **Phase 5–7（生产化）** | OpenAI 的单向架构分层、linter/结构测试、后台自动重构、性能阈值 |
| **贯穿全程** | 一个精简 `AGENTS.md` 地图 + `docs/` 分层 + 可执行计划文档 |

### 4.3 可执行清单（拿来就能做）

- [ ] 写一个 **≤100 行的 `AGENTS.md`**，只当地图，指向 `docs/`
- [ ] 把约定写成 **3–5 条黄金准则**，并尽量用 **linter/pytest 机械强制**（而非写在文档里指望自觉）
- [ ] 关键改动前先写 **可执行计划**（目标/改动文件/约束/验收标准），自己先审
- [ ] 让 agent 走**和你一样的校验流水线**（lint + type + test），且**成功静默、只暴露错误**
- [ ] 评估**独立于生成**：用单独一轮/单独 agent 按**客观标准**验收
- [ ] 长任务用 **context reset + 文件交接**，别硬撑一个长会话到"上下文焦虑"
- [ ] 每次模型升级后，**回头问**：哪些脚手架现在多余了？能拆吗？

---

# 🛠️ 第 5 章 · 两本操作手册（提炼版）

> 把两篇文章的招式，按你戴的两顶帽子重新打包成**可执行清单**。第 4 章给的是"映射到本项目"，这一章给的是"通用怎么做"。

## 5.1 当好「用 agent 的人」（主要源自 OpenAI + HumanLayer）

> **心法**：你的工作不是写代码，是**给 agent 设计一个让它必然写出好代码的环境**。环境的质量 = 代码的质量。

### 七条做法

1. **上下文当"地图"，不当"仓库"**
   - `AGENTS.md` / `CLAUDE.md` 压到 **100 行以内**（HumanLayer 建议 <60），只当导航，指向 `docs/`。
   - 渐进式披露：用到才给，别一股脑塞。
   - ⚠️ 别用自动生成的大文件——ETH 研究显示反而**降 20%+** 性能。

2. **立 3–5 条"黄金准则"，并机械强制**
   - 例：一个概念一个文件、显式优于隐式、在数据边界做校验。
   - 关键：用 **linter / pytest / CI 硬强制**，而不是写进文档指望 agent 自觉。
   - 进阶：让报错信息**内嵌修复指令**，防止 agent 照抄旧的坏模式。

3. **知识全沉淀进仓库（repository-first）**
   - 记住那句：**运行时不在上下文里的东西，对 agent 就不存在**。
   - 文档、schema、约定、可执行计划，全进 git，让 agent 自己能取，而不是靠你复制粘贴。

4. **先写"可执行计划"，再让 agent 动手**
   - 计划含：目标/范围、要改的文件清单、依赖、架构约束、**可测验收标准**。
   - **人先审计划**，再放它执行——把错误挡在写代码之前，而不是写完再返工。

5. **让 agent 走和你一样的校验流水线，且"成功静默、只报错"**
   - lint + 类型检查 + 测试，全自动跑。
   - 关键技巧（context-efficient back-pressure）：**通过就别刷屏，只把失败信息喂回去**——省上下文、防 agent 对着一堆 "PASS" 产生幻觉。

6. **工具少而精**
   - 优先用训练数据里就有的 CLI（`gh`、`docker`、数据库 CLI），**慎装一堆 MCP**——工具描述太多会淹没上下文。
   - 需要时用 **sub-agent 当"上下文防火墙"**，把噪音大的子任务隔离到独立窗口。

7. **Bias towards shipping（按证据配置，别预先设计"理想环境"）**
   - 出现**真实失败**了，才去加对应的 harness 配置；按证据迭代。
   - 别"以防万一"装几十个 skill/规则——那是在给自己加故障面。

### 反模式速查
- 一股脑把所有约定塞进一个大 `CLAUDE.md`。
- "以防万一"装一堆 skill / MCP / hook。
- 每一步都跑全量测试，输出刷屏淹没上下文。
- 规则只写在文档里、没有机械强制（≈ 等于没有）。

### 一句话清单
> **精地图 · 硬规则 · 进仓库 · 先计划 · 静默验证 · 少工具 · 按证据加。**

---

## 5.2 当好「造 agent 的人」（主要源自 Anthropic）

> **心法**：你在设计一个会自己跑很久的"大脑"。它最大的两个敌人是——**上下文会变脏**、**它会过度自信**。你的设计就是在系统性地对抗这两点。
>
> 📌 这些模式**领域无关**，直接适用于你的预约 agent，不只是 coding agent。

### 八条做法

1. **loop 用 TAO + native tool calling**
   - 想→做→看结果的循环（见概念笔记第 1 章），模型返回结构化 `tool_calls`，别让它吐自由文本再人工解析。

2. **管上下文：用 reset + 文件交接，别硬撑长会话**
   - 长任务到一定阶段，**清空窗口 + 用文件做结构化交接**，给 agent 干净白板。
   - 警惕 **context anxiety**：模型快到上限会草草收尾——主动 reset 比等它焦虑强。

3. **把"生成"和"评估"分开——别让 agent 自评**
   - agent 会**过度夸自己的工作**。必须有**独立的 Evaluator**（单独一轮或单独 agent）来验收。

4. **评估要用客观、可测、可打分的标准**
   - 即便是主观维度，也拆成可打分项，并**给关键维度加权**（Anthropic 给"原创性"加权来避免千篇一律）。
   - 措辞会影响产出——精心校准的标准本身就在操舵模型。

5. **让 Evaluator 真正"用"产物去验**
   - Anthropic 用 Playwright **像真实用户一样操作** app。
   - 迁到预约 agent：评估时**真的走一遍完整预约流程**，查最终状态（约到没约到、时间对不对），而不是只信 agent 的自述。

6. **Evaluator 要调教**
   - 要测**边界情况**、查**状态一致性**、产出**带位置的具体反馈**——不是泛泛一句"看起来不错"。

7. **复杂度匹配模型能力——这是最重要的一条**
   - 牢记：**每个组件都编码了一个"模型自己做不到"的假设**。
   - **从简单开始**，只在模型确实做不到时才加脚手架；**模型变强了就回头拆**（Anthropic 随 Opus 升级拆掉了 sprint 拆分、降低了评估频率）。

8. **角色分离 + 契约 + 成本意识**
   - 需要时拆成 Planner（高层规划，防漏范围）/ Generator / Evaluator，**通过文件通信**，动手前先定**成功标准契约**。
   - 记住稳定是有成本的（$9 裸跑 vs $200 全套）——**按任务难度选档位**，不是越复杂越好。

### 反模式速查
- 让 agent 自己说"我做好了"就信。
- 硬撑一个超长上下文，直到它焦虑、丢连贯。
- 一上来就堆满多 agent / 多组件（过度设计）。
- 模型升级后不回头拆脚手架。
- 用"感觉对了"验收，而非可测标准。

### 一句话清单
> **TAO 循环 · 勤 reset · 分离评估 · 客观打分 · 真跑验证 · 复杂度跟着模型走。**

---

## 5.3 两本手册的公共内功

无论戴哪顶帽子，这四条都成立（也是两篇唯一都反复强调的）：

1. **上下文要精、按需供给**——不在上下文 = 不存在。
2. **生成 ≠ 评估**——永远要有外部验证，别自评。
3. **验证要客观可测**——能机器判的就别靠人感觉。
4. **别过度设计**——按证据 / 按模型能力加东西，能拆就拆。

> 这正是概念笔记那个公式的两篇官方注脚：**质量 ≈ (信噪比 × 验证回路) ÷ 故障面**。
> 「用 agent 的人」主要拉高分子里的**验证回路**、压低**故障面**；「造 agent 的人」主要拉高分子里的**信噪比**（上下文管理）和**验证回路**（分离评估）。

---

## 📌 延伸（第三方，非官方）：HumanLayer《Skill Issue》的补充

> 来源：[Skill Issue: Harness Engineering for Coding Agents (HumanLayer)](https://www.humanlayer.dev/blog/skill-issue-harness-engineering-for-coding-agents)。非两篇官方文，但实操性强，与上文互相印证，附几条最有用的：

- 一句话立场：**「It's not a model problem. It's a configuration problem.」**
- **CLAUDE.md/AGENTS.md 越短越好**（理想 <60 行）。引 ETH Zurich 研究：**自动生成**的此类文件让性能**降 20%+**，人手写的只帮约 **4%** → "Less is more" + **渐进式披露**。
- **工具别太多**：太多工具描述会淹没上下文。优先用**训练数据里已有的 CLI**（GitHub/Docker/DB）而非 MCP server。（HumanLayer 把 Linear MCP 换成"CLI 封装 + 6 个用例"，省下数千 token。）
- **Sub-agent 当"上下文防火墙"**：把子任务隔离到独立窗口，防止中间噪音污染主线（对抗 "context rot" / "dumb zone"）。
- **Hooks 做确定性控制**：生命周期事件自动跑校验，**成功静默、只报错**。
- **反模式**：没观察到真实失败就预先设计"理想配置"；"以防万一"装一堆 skill/MCP；过度纠结 sub-agent 工具粒度（"tool thrash"）；每步都跑昂贵全量校验。
- 收尾心法：**「Bias towards shipping.」** 只在真出现失败时才去配 harness，按证据迭代，别按理论。

---

## 术语速查（本篇新增）

| 术语 | 含义 |
|------|------|
| **AGENTS.md / CLAUDE.md** | 注入上下文的项目说明文件；最佳实践是当"地图"而非"规则书" |
| **Golden Principles** | 写进仓库、可机械执行的有主见规则 |
| **Context reset vs Compaction** | 清空窗口+交接 vs 原地压缩历史 |
| **Context anxiety** | 模型快到上下文上限时草草收尾的倾向 |
| **GAN-inspired agents** | Planner/Generator/Evaluator 分离，生成与评估对抗 |
| **Sprint contract** | 动手前协商好的成功标准+可测行为 |
| **Executable plan** | 带验收标准、可被人审的结构化任务计划 |
| **Repository-first** | 知识全部以仓库 artifact 形式存在（不在上下文=不存在） |
| **Under-scoping** | 单 agent 容易漏掉功能范围的毛病 |
| **Generic AI slop** | 千篇一律、缺乏原创的 AI 产出 |

---

## 参考来源

- OpenAI — [Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/)（原文，本次抓取 403）
- Anthropic — [Harness Design for Long-Running Application Development](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [OpenAI Introduces Harness Engineering: Codex Agents Power Large-Scale Software Development (InfoQ)](https://www.infoq.com/news/2026/02/openai-harness-engineering-codex/)
- [What Is Harness Engineering for AI Agents? (Milvus)](https://milvus.io/blog/harness-engineering-ai-agents.md)
- [Harness Engineering: The Complete Guide (ZBuild)](https://www.zbuild.io/resources/news/harness-engineering-complete-guide-ai-agent-codex-2026)
- [Skill Issue: Harness Engineering for Coding Agents (HumanLayer)](https://www.humanlayer.dev/blog/skill-issue-harness-engineering-for-coding-agents)
