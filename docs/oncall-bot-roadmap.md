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

**状态**：✅ 实现完成、真租户端到端已验证，待归档 →
`openspec/changes/feishu-channel-integration/`（proposal / design / specs×5 / tasks）

已在飞书群 `oncall-bot test` 跑通：@bot 多轮对话（话题内 6 轮收敛到同一 session）、
会话隔离、先 ack 后结果（实测间隔 31s）、超时兜底带副作用提示、排队上限提示。
分支 `feat/feishu-executor`。

**实测校正的三处设计错误**（都是"逻辑上说得通、只有真数据能证伪"的那类）：
1. `thread_id` 排在会话键解析链首位会**切断多轮**——它只出现在续话消息上，首条没有，
   于是首条与其回复落到不同 session。正解是 `root_id → message_id`
2. `lark_oapi.ws.Client.start()` 用自己的模块级 loop `run_until_complete`，在 FastAPI
   lifespan 里会抛 "loop is already running"；更隐蔽的是那个 loop 是 **import 时**抓的，
   `_connect()` 用它 `create_task` 起收包循环 → 在 FastAPI 下收包 task 永不执行，
   表现为"连上了但一条事件都收不到且不报错"。必须建连前重绑到运行中的 loop
3. `JsonFormatter` 把 `extra={...}` **全部丢弃**，全应用的结构化字段等于白写——为实测
   特意加的诊断字段一个都没输出，只能改从数据库反查

**范围**：只做管道，不加新功能。做完的效果是「现有预约 Agent 原封不动出现在飞书群里，能多轮对话、话题隔离」。

- 新增 `executor/`：两种执行模式（`submit + 回调` 异步 / `execute_inline` 同步透传）、同话题串行 / 跨话题并行（上限默认 10）、每会话排队深度上限、墙钟总超时 600s、五种终态
- 新增 `channels/lark/`：lark-oapi 长连接订阅 `im.message.receive_v1`、event_id 去重、会话键解析（`thread_id → root_id → message_id`）落 DB、双层 ack、结果投递 + 失败重试（**绝不静默**）
- 改造 Web 接线走 executor 同步内联，带环境变量开关可回滚
- 预约工具不动；`harness` 仅补工具超时（`Tool.timeout` + `_dispatch`）；`uv run pytest` + evals 门禁必须全绿

**设计评审的九处修正：✅ 已落到文件**（2026-07-27）

超时归属：
- 删除「LLM 请求级 hang 看门狗」需求——该能力已存在于 `guardrails/retry.py:guarded_invoke`（30s / 3 次 / 指数退避），写成新需求会误导实现
- 改为「工具调用超时」，且**超时值声明在 `Tool` 上而非运行时全局常量**：主 registry 只注册了 `delegate` 一个工具，而它的 handler 内部跑的是整个子 AgentLoop（8 步 × 每步 30s×3 重试），全局 60s 会误杀正常任务。`delegate` 显式豁免
- 明写超时的适用边界：`asyncio.wait_for` 中断不了同步阻塞调用，同步工具须自行下沉线程池——否则第 3 期移植 `repokit.py` 的 git 子进程时会误以为有保护
- `design.md` D3 改写为「超时分三层」对照表（墙钟 600s / 工具 60s / LLM 30s）

执行模型：
- executor 改为**两种模式**：Web 走 `execute_inline`（请求协程内跑、generator 直接透传），IM 走 `submit`。理由是把 Web 塞进 worker 队列会凭空引入背压 / 断连语义 / 异常跨协程重抛三个问题，而本期硬要求恰是 Web 行为不变。取消 `TaskHandle` 概念
- 非成功终态**必须补写兜底 assistant 回合**：现有编排先写 user 回合再跑 loop，中途 cancel 会留下永远配不上回复的孤立 user 回合，破坏「历史成对」这个短期记忆与摘要压缩的隐含前提。`CancelledError` 补写后必须重抛
- 新增每会话排队深度上限（默认 5）：同话题串行下用户连发会排队并投递多条回复，刷屏且无界堆积

验证与接入：
- **`evals/` 证明不了 Web 改道无回归**——`evals/agent_capture.py` 直接构造 `AgentLoop`，不经 `chat_handler`/`web`/executor。原 tasks 里「改道前后跑 evals 做 A/B 比对」是假阳性安慰（两次跑的是同一条不受影响的路径）。改为新增 HTTP 端到端回归测试（TestClient + fake LLM）
- **不能假设消息带 `thread_id`**——它只在话题模式群下发，普通群 @bot 只有 `chat_id`/`message_id`/`root_id`。会话键改为优先级链，且**实施上强制「先打真实事件载荷、后建表」**
- 群聊要把发送者 open_id 当 `user_id` 传进去，否则 34 人的长期偏好会混成一个 `default_user`
- 长连接跑 FastAPI 同进程 + **硬约束单 worker**（多 worker 会起多份长连接重复消费，进程内去重表拦不住）

**前置条件（用户操作）**：飞书开放平台创建应用，取得 app_id / app_secret，开通 im 消息收发权限。executor 部分不依赖此项，可先开工。

**实施顺序**：executor + `Tool.timeout` → Web 接线切换（**新增的 HTTP e2e 测试**证明无回归，evals 只证明 AgentLoop 没坏）→ 真租户打一条事件载荷确认字段 → 飞书 gateway/delivery（fake client 单测）→ consumer 接真租户端到端验证。

---

## 第 1.5 期：退役旧意图分类器（独立小 change，可与第 1 期并行）

**状态**：✅ 已归档（commit `1906499`，2026-07-27）→ `openspec/changes/archive/2026-07-27-retire-legacy-intent-classifier/`

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
