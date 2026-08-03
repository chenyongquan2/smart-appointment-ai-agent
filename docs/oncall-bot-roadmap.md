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

1. **换域 = 换五样东西**：工具集 + **子 Agent 集** + system prompt + 权限策略 + eval 数据集。运行时（TAO 循环、记忆、护栏、Tracer）一行不动。（原写四样，第 2 期落地时发现子 Agent 也是域绑定的——预约域有三个专员、值守域一个都不该有，见 `domains/oncall/subagents/__init__.py` 的理由。）
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

## ⛔ 贯穿性决策：预约域评测冻结（2026-08-02）

**不再向预约域的评测投入任何新精力。** 预约域是要退役的，为一个将退役的域打磨评估数据没有回报。

具体三条：

1. **不恢复 `evals-dataset-scaleup-v2`**（分支 `feat/evals-dataset-scaleup`，17/18 完成、卡在重定基线）。它剩的活是一次约 64 分钟、数百次真实 LLM 调用的跑批，产出是"184 条**按摩预约**用例的更紧置信区间"。原先卡在"等独立 RAG 接入"，现在的答案不是等，是**放弃**。分支保持不合并，到第 4 期正式 close。数据集扩容的方法论已写进 `evals/README.md` 与 `docs/agent-eval-fieldguide.md`，知识留下了，只是那 184 条句子不进主干。
2. **不重定基线、不扩数据集、不补预约域用例**。现有 51 条与 `baseline.json` 原样冻结。
3. **预约域 evals 在第 2、3 期的定位降级为"零成本的运行时回归网"**——它衡量的是域无关运行时（TAO 循环 / ToolRegistry / 记忆 / 护栏）有没有被改坏，**不是**衡量 oncall 能力（它衡量不了：工具名都不同，`工具调用-F1` 与 oncall 不可比）。留着只因为不删的成本是零；一旦需要为它花时间，直接跳过。

⚠ **随之而来的代价，别自欺**：本文档第 2 期原写"搬迁后现有 pytest + evals 门禁全绿即证明无损"。冻结后实际的网只剩 pytest（fake LLM，**不会推理"该调哪个工具"**）+ 至多跑一次现有 gate。工具层重构后"模型是否仍选对工具"这件事，覆盖是弱的。接受这个风险，是因为投入产出不划算，不是因为风险不存在。

**什么时候才重新谈评测**：第 4 期，用 oncall 的真实排障对话建新数据集。届时**复用机制、重建数据**——`evals/` 的多采样 t-CI、门禁、dev/held-out 切分、任务成功率口径、trace triage 闭环、并发 runner 全部域无关可搬；域绑定的只有 `cases.jsonl` 与 `baseline.json` 两个文件。改造 1–8 没有白做。

---

## 第 1 期：飞书 Channel + 任务执行层

**状态**：✅ 已归档 → `openspec/changes/archive/2026-07-30-feishu-channel-integration/`（proposal / design / specs×5 / tasks），已合并进 master

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

**状态**：✅ 已完成 → change `domain-packages`（2026-08-02）。`domains/appointment/` 五槽位齐全（工具集 / 子 Agent / 人设 / 权限策略 / 评估数据），`AGENT_DOMAIN` 缺省 `appointment`；`agents/` 遗留层约 2031 行已删（BREAKING：`/api/appointment`、`/api/user_behavior_analysis` 及对应页面下线）；`TechnicianFinder` 下沉 `services/`，工具层对 `agents/` 的横向依赖债还清。

顺带**首次把权限闸门接进生产路径**——此前 `ToolRegistry` 从未收到过 policy，实际一直走 `allow_all` 默认。oncall 的只读红线要靠它硬 enforce，故在纯搬迁这期把管道通了并留测试守着。

⚠ **发现三处剩余域泄漏**（记忆层的 `summary_schema.py` / `summary.py` / `long_term.py` 里嵌了预约域的提示词与枚举）。它们不是"放错位置的域内容"，而是"域无关机制里嵌了域特定文本"，要清干净得让这些文本随域可配——属行为变更，越出本期纯搬迁纪律。已写进 `tests/test_domain_loading.py` 的白名单（清掉后测试会提醒删白名单），第 3 期做 oncall 域时按需处理。

**目标**：把「域」收敛成可装载的包，为 oncall 域腾出位置。

- 新增 `domains/` 结构：`tools/`（工具集）、`prompts/`（system prompt）、`policy.py`（权限策略）、`evals/`（用例集 + baseline）
- 现有预约域整体下沉为 `domains/appointment/`（纯搬迁，行为不变）
- 领域包**按配置装载**，运行时代码里 MUST NOT 出现 `if domain == ...`
- 顺带清掉 pre-harness 的 `agents/` 遗留层（约 2031 行：`appointment_agent` + `appointment/` + `user_behavior_agent` + `user_behavior/`，及喂它们的遗留端点）。**前置**：`harness/tools/technician.py` 仍横向依赖 `agents/appointment/technician_finder.py`（Phase 2 就记下的已知取舍，注释里写着"Phase 3 迁移技师查找逻辑下沉后即可去除"），须先把 `TechnicianFinder` 下沉到 `services/`。反正都是搬，一次搬到位
- 验证：搬迁后 pytest 全绿。~~evals 门禁~~ → 见上文「预约域评测冻结」，evals 至多跑一次现有 gate，不为它投入新精力

---

## 第 3 期：OnCall 工具集与服务层

**分三个切片做**（整期一次做完太大，一个审阅闸门扛不住）：

| 切片 | 内容 | 状态 |
|---|---|---|
| 1 | oncall 域骨架 + `services/vlog.py` + `vlog_query` + 排查知识按需加载 | ✅ change `oncall-domain-vlog`（2026-08-02） |
| 2 | `services/repo.py`（`repokit.py` 669 行）+ `code_analysis` | 待做 |
| 3 | `services/docs_search.py`（MT4/MT5 FTS）+ `mt_docs_search` | 待做 |

**切片 1 已完成**：`AGENT_DOMAIN=oncall` 即切到值守域（2 个只读工具、只读策略硬 enforce、
4 份排查资料按需加载）。`probe.py` 的传输层从同步 `urllib` 换成 async httpx——**照搬就是
第三次重演阻塞缺陷**（前两次：知识库检索、技师专长匹配）。

⚠ **切片 1 的冒烟发现并修掉一处第 2 期遗留缺陷**：主 registry 的形状此前写死为「只放
delegate」，那其实是**预约域的结构**而非运行时不变量。装上无子 Agent 的值守域会得到一个
「只有 delegate、却无处可派」的主 Agent——域的工具够不着且不报错。已改为
`domains.build_main_registry` 按 `len(domain.subagents)` 决定形状（判的是结构属性、
不是域名，运行时对域仍然无知）。

⚠ **切片 1 的验收边界**：离线测试证明的是「请求构造正确、异步不阻塞、失败分类正确、
vmui URL 往返一致」；**「查得对不对」需真实凭据 + 内网手动冒烟**，CI 做不到。

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

1. 读本文档（**尤其是开头的「预约域评测冻结」决策**）+ `openspec/project.md`（黄金准则）
2. `openspec list` 看有无 active change；第 1 / 1.5 期已归档并合并，当前应从**第 2 期**起步
3. 各期：`/opsx:propose` 起新 change，范围照本文档对应小节 → 人审 → `/opsx:apply` → 验证 → `/opsx:archive`
4. 别做的事：恢复 `feat/evals-dataset-scaleup`、重定 `evals/baseline.json`、给预约域补用例——见「预约域评测冻结」
