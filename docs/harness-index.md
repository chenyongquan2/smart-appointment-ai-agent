# 🧭 Harness 学习地图（总索引）

> 这是一个关于 **Agent Harness** 的学习系列总入口。所有相关笔记从这里进，按下面的顺序读最顺。
>
> **一句话定调**：模型负责**推理（reasoning）**，harness 负责**能力（capability）**——投资你的 harness，而不是只换你的模型。

---

## 📚 按顺序读（三步走）

| # | 文档 | 它管什么 | 什么时候读 |
|---|------|---------|-----------|
| 1️⃣ | [概念入门 · harness-study-notes.md](./harness-study-notes.md) | harness **是什么**、三层 ①②③、家族全景、马挽具比喻、5 杠杆、要不要装 ECC | **第一次接触**这个概念时 |
| 2️⃣ | [官方手册 · harness-engineering-official-notes.md](./harness-engineering-official-notes.md) | OpenAI / Anthropic 两篇官方文精读 + **两份操作手册**（当好"用 agent 的人 / 造 agent 的人"） | 想知道**高手具体怎么做**时 |
| 3️⃣ | [重构计划 · harness-refactor-plan.md](./harness-refactor-plan.md) | 把本预约项目从 **workflow 重构成 harness** 的分 Phase 落地方案 | **动手改本项目**时 |

> 简记：**1 学概念 → 2 学方法 → 3 动手做**。

---

## 🗺️ 30 秒先建立两个心智模型

读任何一篇前，先记住这两张"地图"，后面就不会绕晕：

**① 三层 harness（在哪一层）**

| 层 | 是什么 | 例子 |
|----|--------|------|
| ① 运行时 harness | 嵌进**你 app** 的 agent 大脑 | 你重构后的预约系统 |
| ② 编码工具 | 帮你**写代码**的 agent | Claude Code、Cursor、Codex |
| ③ 增强层 | 装在 ② 之上的能力包 | ECC |

**② 两篇官方文的分工（A/B）**

- 🅰️ **OpenAI** = 当好"**用 agent 的人**"（开发期，harness 住在代码仓库里）
- 🅱️ **Anthropic** = 当好"**造 agent 的人**"（运行期，harness 住在 agent 大脑里）

---

## ⚡ 想干嘛就跳哪（快速路由）

- 只想用一句话搞懂 harness → [概念笔记 · 5 分钟速览](./harness-study-notes.md#-怎么读这份笔记)
- 纠结要不要装 ECC 这类增强包 → [概念笔记 · 第 6–7 章](./harness-study-notes.md)
- 想要"怎么把代码写好"的清单 → [官方笔记 · 5.1 当好用 agent 的人](./harness-engineering-official-notes.md)
- 想要"怎么设计 agent 更稳"的清单 → [官方笔记 · 5.2 当好造 agent 的人](./harness-engineering-official-notes.md)
- 准备改本项目了 → [重构计划](./harness-refactor-plan.md)

---

## 🔗 相关（非 harness 主线）

- [LangChain LCEL `|` 写法笔记](./langchain-lcel-notes.md) —— 重构会用到 LangChain，这篇讲 `prompt | llm` 的原理，新手向。

---

> 维护约定：**一个概念一个文件**（这正是 OpenAI 黄金准则之一）。以后新增 harness 相关笔记，只需在本页"按顺序读"表里加一行，别把内容塞进已有文件。
