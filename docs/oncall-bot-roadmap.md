# OnCall Bot 改造路线图（IM 接入 → 领域包化 → 评估闭环）

> 本文档是「把现有预约 Agent harness 落地为公司 Lark/飞书 OnCall 值守机器人」的多期改造路线。
> 与 [harness-refactor-plan.md](harness-refactor-plan.md)（Phase 0–7，已完成）并列：那份是「把 workflow 重构成 harness」，
> 这份是「把 harness 换域落地到生产 IM 场景」。
> 开发方式不变：每期走一个 OpenSpec change，`/opsx:propose` → 人审 → `/opsx:apply` → 验证 → `/opsx:archive`。

## 背景与动机

- 现状：harness 重构完成（TAO 循环、ToolRegistry、三层记忆、护栏、Tracer、三层 evals + CI 门禁），但只有 Web 一个入口，领域是「按摩预约」。
- 目标：把域无关的运行时复用到公司真实的 OnCall 值守场景（查日志 → 根因分析 → 回话题），落到飞书/Lark 群里给同事使用。
- 参考系统：`C:\workspace\lark-oncall-bot`（生产级 Lark 值守 bot，已在 34 人群运行）。它趟平了 IM 接入与生产韧性的坑，但**零测试、零 evals**；本项目的 evals 体系正是它的短板，两者互补。

## 核心设计判断（贯穿各期，勿翻案）

1. **换域 = 换四样东西**：工具集 + system prompt + 权限策略 + eval 数据集。运行时（TAO 循环、记忆、护栏、Tracer）一行不动。
2. **Channel 层的判据**：换掉飞书换成钉钉/企微，Agent 层零改动才算分层干净。
3. **Channel 与 Agent 之间是任务式接口**，不是同步调用。IM 是「秒回 ack + 异步投递」，Web 是它的同步特例。
4. **不需要外部 hang 看门狗**：`harness/guardrails/retry.py` 的 `asyncio.wait_for(ainvoke, 30s)` + 指数退避已覆盖 LLM 请求级 hang。lark-oncall-bot 需要它是因为 AI 跑在 opencode 子进程里、父进程看不见内部；本项目进程内 await 天然满足。
5. **不采纳 lark-oncall-bot 的冷启子进程架构**：本项目有完整 harness，进程内常驻的可观测性与可测性更好。同理不采纳它的 TSV/JSON 状态存储（本项目有 DB 层）与零 pip 依赖自我约束。
6. **凭据集中在确定性服务层，绝不进 LLM 上下文**；oncall 工具全部只读（代码绝不改、绝不提 PR），红线靠 `harness/guardrails/permission.py` 硬 enforce，不靠 prompt 自觉。
7. **services 层扩展遵循开闭原则**：新能力碰新外部系统 → 新增 service 文件；不改已有 service。

## 目标架构（6 层）

```
channels/            ← 新增：多 IM 入口并列，web 降级为 channel 之一
  web/               现有 FastAPI（改走任务接口，对外行为不变）
  lark/              飞书/Lark（同构，域名可配）
executor/            ← 新增：任务执行层（排队 / 并发上限 / 墙钟超时）
harness/             不动：TAO 循环 · 记忆 · 护栏 · Tracer（域无关运行时）
domains/             ← 新增概念：可替换的领域包（工具 + prompt + 权限 + evals）
  appointment/       现有预约域下沉
  oncall/            新增值守域
services/            仅新增文件：vlog / repo / docs_search
db/                  新增 channel_session 映射表
config/              新增飞书凭据、并发与超时参数
```

---

## 第 1 期：飞书 Channel + 任务执行层

**状态**：proposal 已生成，待人审 →
`openspec/changes/feishu-channel-integration/`（proposal / design / specs×2 / tasks）

**范围**：只做管道，不加新功能。做完的效果是「现有预约 Agent 原封不动出现在飞书群里，能多轮对话、话题隔离」。

- 新增 `executor/`：任务式接口（`submit → TaskHandle`）、同话题串行 / 跨话题并行（上限默认 10）、墙钟总超时 600s、四种终态（成功/失败/超时/guardrail 耗尽）
- 新增 `channels/lark/`：lark-oapi 长连接订阅 `im.message.receive_v1`、event_id 去重、`thread_id → session_id` 映射（落 DB）、秒回 ack、结果投递 + 失败重试（**绝不静默**）
- 改造 Web 接线走 executor 同步特例，带环境变量开关可回滚
- harness 与预约工具不动；`uv run pytest` + evals 门禁必须全绿

**apply 前需先修正的两处**（上下文中已确认，尚未落到文件）：
- 删除 `specs/task-executor/spec.md` 中「LLM 请求级 hang 看门狗」需求——该能力已存在于 `guarded_invoke`，写成新需求会误导实现
- 改为新增「工具调用超时」需求：`harness/runtime/agent_loop.py:244` 的 `_dispatch` 目前只 catch 异常、**无超时**；接 oncall 网络工具（VictoriaLogs / git）后是真实挂死风险。超时后把「工具超时」当错误结果回灌（**不重试**，工具有副作用）
- 同步更新 `design.md` D3 的表述

**前置条件（用户操作）**：飞书开放平台创建应用，取得 app_id / app_secret，开通 im 消息收发权限。executor 部分不依赖此项，可先开工。

**实施顺序**：executor → Web 接线切换（现有 pytest + evals 证明无回归）→ 飞书 gateway/delivery（fake client 单测）→ consumer 接真租户端到端验证。

---

## 第 1.5 期：退役旧意图分类器（独立小 change，可与第 1 期并行）

**状态**：proposal 已生成，待人审 → `openspec/changes/retire-legacy-intent-classifier/`

旧分类器已退出主服务链路但仍被 evals 门禁守护（守假目标）。一揽子：删组件/端点/测试 → 意图准确率指标退役（工具 name 级 F1 已覆盖同一信号，不做反推替代）→ `GATED_METRICS` 3→2 项 → 延迟指标改真端到端口径（原实测为分类器调用耗时）→ 重定基线。`expected_intent` 标签保留为数据集元数据。

## 第 2 期：领域包化（domains/）

**目标**：把「域」收敛成可装载的包，为 oncall 域腾出位置。

- 新增 `domains/` 结构：`tools/`（工具集）、`prompts/`（system prompt）、`policy.py`（权限策略）、`evals/`（用例集 + baseline）
- 现有预约域整体下沉为 `domains/appointment/`（纯搬迁，行为不变）
- 领域包**按配置装载**，运行时代码里 MUST NOT 出现 `if domain == ...`
- 验证：搬迁后现有 pytest + evals 门禁全绿即证明无损

---

## 第 3 期：OnCall 工具集与服务层

**目标**：真正能用的值守能力。大量代码可从 `lark-oncall-bot` 移植。

- `services/vlog.py` ← 移植 `probe.py`（381 行）：VictoriaLogs 查询、env→租户映射、代理绕行、vmui URL 解析、**error 自动下钻**
- `services/repo.py` ← 移植 `repokit.py`（669 行）：git 只读、per-env 常驻 detached worktree
- `services/docs_search.py` ← 复用 `mt4docs.db`（479KB）/ `mt5api.db`（12MB）两个 SQLite FTS 库 + 约 2.6 万行 markdown 语料
- `domains/oncall/tools/`：`vlog_query` / `code_analysis` / `mt_docs_search`（薄封装）
- `domains/oncall/prompts/`：值守人设与红线
- `domains/oncall/policy.py`：全工具只读，凭据不进上下文
- 一并移植它的**领域知识沉淀**（比代码更值钱）：vlog-query SKILL 的 150 行查询经验（MT 错误码分层查、告警时区坑）、服务 profile / 错误码 reference 的按需加载路由表（避免整库塞上下文）
- 注意 Lark 身份模型坑：读话题历史必须 user 身份，bot 身份读会被拒 230027；user token 约每周需刷新

---

## 第 4 期：OnCall 评估闭环（本项目相对参考系统的净增量）

**目标**：把三层 evals 体系搬到 oncall 域，让「Agent 是否变好」可度量。

- 从真实排障对话构建 oncall 用例集（dev / held-out 切分），真值人工标注
- 定义 oncall 版任务成功率口径（如「根因定位是否正确」），保留诚实边界标注
- Tracer → trace 落盘 → triage 客观失控信号（guardrail 耗尽 / 打转 / 工具失败 / max_steps）→ 人审回灌 → 重定基线
- CI 门禁守正确性子集

---

## 后续可选演进（不排期）

- **多平台**：飞书与 Lark 是同一套 API（`open.feishu.cn` / `open.larksuite.com`），代码一份跑两实例，`session_id` 用 `{channel}:{thread_id}` 命名空间隔离；真正异构的钉钉/企微/Slack 才需要新 Channel 目录
- **多模型分级降本**：参考 lark-oncall-bot（deepseek 执行 / haiku 检索 / sonnet 分析），本项目 `config/model_provider.py` 已有 Provider 抽象，加分级路由成本不高
- **任务持久化**：当前 executor 为进程内 asyncio，crash 时在途任务丢失（初期接受）；需要时把任务表落 DB
- **Executor 拆独立服务**：接口已抽象，届时把进程内调用换成 HTTP/队列即可
- **身份映射**：跨平台同一用户是不同 user_id，长期偏好记忆若要跨平台合并再设计

## 新对话如何续上

1. 读本文档 + `openspec/project.md`（黄金准则）
2. `openspec status --change feishu-channel-integration` 看第 1 期进度
3. 第 1 期：先落实上文「apply 前需先修正的两处」，再 `/opsx:apply`
4. 后续各期：`/opsx:propose` 起新 change，范围照本文档对应小节
