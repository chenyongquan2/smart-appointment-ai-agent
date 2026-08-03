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

⚠ **发现三处剩余域泄漏**（记忆层的 `summary_schema.py` / `summary.py` / `long_term.py` 里嵌了预约域的提示词与枚举）。它们不是"放错位置的域内容"，而是"域无关机制里嵌了域特定文本"，要清干净得让这些文本随域可配——属行为变更，越出本期纯搬迁纪律。已写进 `tests/test_domain_loading.py` 的白名单（清掉后测试会提醒删白名单）。

> **📌 后续（2026-08-03 更新）**：第 3 期并未处理它——值守域上线时这三处仍在，即 oncall
> 的会话摘要确实拿着按摩例子在跑。**但结论是"暂不单独立项"**：正解取决于预约域是否退役，
> 若退役则从"加配置槽位"退化成"直接换文本"。理由与触发条件见文末「处理顺序」。

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
| 2 | `services/repo.py` + `locate_service_code` / `code_search` / `read_source` | ✅ change `oncall-domain-code`（2026-08-02） |
| 3 | `services/mt_docs.py`（MT4/MT5 FTS）+ `mt_docs_search` | ✅ change `oncall-domain-mtdocs`（2026-08-02） |

> ✅ **两项真实环境冒烟已于 2026-08-03 全部通过**（详见各 change 的 tasks 末节）。
> 日志查询：三租户并发、uat/dev 各命中数百万条真日志。源码定位：真实 OCS4 与 OCS5
> 仓库上定位→检索→读片段→jail 四项全过。**两项冒烟共暴露 4 处离线测试发现不了的
> 缺陷**（prod 宽窗"0 命中"其实是没算完；全局分支候选对真实仓库全不匹配；同仓多服务
> worktree 撞车；声明映射后仍回退会捡到别的服务的分支），均已修复并补回归测试。
>
> 🔬 **重跑方式**：`uv run python scripts/oncall_smoke.py`
> （只跑一项用 `--only vlog` / `--only repo`）。脚本本身已用合成仓库自测通过，
> 故跑出来失败即为环境问题、不是脚本 bug。**前置**：`.env` 里填 `VM_LOGS_*`；
> 把某个服务仓库 `git clone --mirror` 进 `repos/<服务名>/.git-mirror`
> （agent 没有 clone 能力，那是写操作——见切片 2 的 design D2）。

**第 3 期三片全部完成。** 值守域现有**六个只读工具**：日志查询 · 资料加载 · 源码定位 · 源码检索 · 源码阅读 · MT 文档检索。

**切片 3 已完成**：复用参考系统现成的两个 FTS 库（`mt4docs.db` 468K / `mt5api.db` 12M），**不重建语料**。三点值得记：
- **为什么不直接让 AI 读 `/mt4-api-docs` skill**：那是 *Claude Code* 的 skill（装在 `~/.claude/skills/`），参考系统用的是 *opencode* 的 skill 机制。值守 bot 是本项目 harness 里的 agent——**没有 skill 机制、没有通用文件系统工具**，且 `~/.claude/skills/` 在部署的服务器上根本不存在。也不打算为此补 skill 机制：skill 的不可替代之处是"程序性指令多到要按情形动态加载"，而这里要的是检索，FTS 正是干这个的。
- **12M 的库不进版本库**，走 `ONCALL_MT_DOCS_DIR` 配置；未配置时**明确报配置缺失**而非返回空——空结果会被模型读成"文档里没有这个码"，进而编造 API 语义。
- **真库验证抓到两处**：① 摘录取成了 URL（`snippet(-1)` 是"命中哪列取哪列"，而 URL 里常含关键词）→ 改为固定取描述列；② 两个库装的都是 **Manager API**、不是 MQL 语言参考，拿 `OrderSend` 去查是 0 命中——模型不知道这个边界会把"不在库范围内"误报成"该 API 不存在"，已写进 description 与 prompt。

⚠ **切片 3 与前两片不同：它不依赖内网或凭据，已端到端验证过**（配上真实库路径跑通了 registry → 工具 → service → FTS 全链路）。

**切片 2 已完成**：值守域现有**五个只读工具**。这里有个比"移植 669 行"更根本的问题：参考系统里 `code-analysis` = repokit 定位 worktree + **agent 用自己的文件系统工具去 grep/读**，而本项目的 harness **不给模型文件系统工具**——只移植 repokit 会得到一个"返回了路径但读不了"的死工具。故新写了两个**受管束的只读检索工具**（`code_search` / `read_source`），三重 jail：只收相对路径、`resolve()` 之后判子树（故挡得住 symlink）、`repo_dir` 只认 `repos/` 下纯目录名。

**刻意不做 clone**：那是写操作，标 `dangerous=True` 就会被值守域的只读策略直接拒掉。参考系统靠"clone 前硬确认 + 埋锚点"这套人工闸门兜，本项目的答案更简单——agent 根本不 clone，仓库由运维预先备好，落空时返回 `need_clone` 引导状态。红线不打折，也省掉一整套确认机制。

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

> 以下**「落地实际」一列是收尾后对账过的**（2026-08-03）。原设想一列保留，因为差异本身是信息：
> 工具从设想的 3 个变成 6 个，是因为本项目不给模型文件系统工具（见切片 2 的说明）。

| 原设想 | 落地实际 |
|---|---|
| `services/vlog.py` ← 移植 `probe.py`（381 行） | ✅ [services/vlog.py](../services/vlog.py)（623 行）：VictoriaLogs 查询、env→租户映射、代理绕行、vmui URL 解析、error 自动下钻、**宽窗+正则预检闸门**、**单 env 总时长上限** |
| `services/repo.py` ← 移植 `repokit.py`（669 行） | ✅ [services/repo.py](../services/repo.py)（382 行，只移植只读部分、不含 clone） |
| `services/docs_search.py` | ✅ 改名 [services/mt_docs.py](../services/mt_docs.py)（157 行）——它只管 MT4/MT5 两个 FTS 库，叫 `docs_search` 会让人以为是通用文档检索 |
| `domains/oncall/tools/`：`vlog_query` / `code_analysis` / `mt_docs_search`（3 个） | ✅ **6 个**：`vlog_query` · `load_reference` · `locate_service_code` · `code_search` · `read_source` · `mt_docs_search`。`code_analysis` 这个名字从未存在——它在参考系统里是「定位 worktree + agent 自己拿文件系统工具 grep」，本项目不给文件系统工具，故拆成受管束的三个 |
| `domains/oncall/prompts/` | ✅ 单文件 [domains/oncall/prompt.py](../domains/oncall/prompt.py)（95 行）——一个域一份人设，不需要目录 |
| `domains/oncall/policy.py` | ✅ 全工具只读，凭据不进上下文，硬 enforce |
| 移植领域知识沉淀 | ✅ [domains/oncall/references/](../domains/oncall/references/) 4 份、约 1300 行（服务 profile + MT/OCS4/OCS5 错误码），按需加载。⚠ 服务 profile 里 OCS4/OCS5 的**口语别名仍有 2 处 `<待填>`**，需内部知识填写；机制上安全（prompt 与 tool description 都明说标 `<待填>` 者不得当真），代价是"清算4"这类口语匹配不上服务 |

**⏸ 明确暂缓：读 Lark 话题历史（user 身份 / 230027）**

原文这条写成"注意事项"，但它其实是个**未实现的能力**，且本期收尾时没交代——现在明确它的状态：
`channels/lark/` 里零 history / list_message 调用，bot 的上下文**完全来自自己的 DB session**。
即：话题里 @bot 之前的对话、以及同事之间没 @bot 的讨论，bot 看不见。

不做的理由：成本大头在**运维不在代码**——user token 约每周需人工刷新（bot 身份读会被拒 230027）。
为一个尚未证实的问题上一道每周的人工负担，不划算。

**触发判据**（满足任一即立项，不要凭感觉提前做）：
真实群里出现 ≥3 次"因为看不见上文而答错或反问用户已经说过的信息"，或 trace triage 里
"用户补述上下文"成为高频模式。届时先评估更便宜的替代（如引导用户 @bot 时带上关键信息）。

---

## 第 4 期：OnCall 评估闭环（本项目相对参考系统的净增量）

**目标**：把三层 evals 体系搬到 oncall 域，让「Agent 是否变好」可度量。

**⚠ 前置是真实流量，不是代码。** 数据集要真实排障对话；而**采集是零成本自动进行的**——
trace 落盘已接在生产路径上（[api/chat_handler.py](../api/chat_handler.py) 的
`SamplingSpanExporter` 包 `FileSpanExporter`，命中失控信号的 trace 不受采样率影响必留），
[evals/triage.py](../evals/triage.py) 也已就位。所以第 4 期**不需要先补埋点，需要先有量**。

**建议拆两半做，先做不需要人工标注的那半**：

- **上半（便宜，随流量即可开工）**：对真实 trace 跑 triage，统计客观失控信号
  （guardrail 耗尽 / 打转 / 工具失败 / max_steps）。零标注成本，产出是"哪里在坏"。
  它顺带回答几个目前只能猜的问题——比如记忆层三处域泄漏（预约例子污染 oncall 摘要）
  到底有没有真掉链子，摘要坏了会在 trace 里看得见。
- **下半（贵，要人工标真值）**：构建 oncall 用例集（dev / held-out 切分）、定义 oncall 版
  任务成功率口径（如「根因定位是否正确」，保留诚实边界标注）、人审回灌重定基线、
  CI 门禁守正确性子集。等对话攒够再做。

---

## 后续可选演进（不排期）

- **多平台**：飞书与 Lark 是同一套 API（`open.feishu.cn` / `open.larksuite.com`），代码一份跑两实例，`session_id` 用 `{channel}:{thread_id}` 命名空间隔离；真正异构的钉钉/企微/Slack 才需要新 Channel 目录
- **多模型分级降本**：参考 lark-oncall-bot（deepseek 执行 / haiku 检索 / sonnet 分析），本项目 `config/model_provider.py` 已有 Provider 抽象，加分级路由成本不高
- **任务持久化**：当前 executor 为进程内 asyncio，crash 时在途任务丢失（初期接受）；需要时把任务表落 DB
- **Executor 拆独立服务**：接口已抽象，届时把进程内调用换成 HTTP/队列即可
- **身份映射**：跨平台同一用户是不同 user_id，长期偏好记忆若要跨平台合并再设计

## 新对话如何续上

**当前状态一句话**（2026-08-03 对账）：第 1 / 1.5 / 2 / 3 期全部完成并合并，值守域六个只读工具
经真实环境冒烟 + 真实群聊验证。`uv run pytest` 578 passed / 1 skipped。**下一步的瓶颈是真实流量，
不是代码**——见下方"处理顺序"。

1. 读本文档（**尤其是开头的「预约域评测冻结」决策**）+ `openspec/project.md`（黄金准则）
2. `openspec list` 会列出 `evals-dataset-scaleup-v2`——**那是已放弃的，不是在做的**
   （见它 proposal.md 顶部的状态说明）。除它之外无 active change。
3. 各期：`/opsx:propose` 起新 change，范围照本文档对应小节 → 人审 → `/opsx:apply` → 验证 → `/opsx:archive`
4. 别做的事：恢复 `feat/evals-dataset-scaleup`、重定 `evals/baseline.json`、给预约域补用例——见「预约域评测冻结」

### 处理顺序（2026-08-03 定）

**核心判断：瓶颈是真实流量。** 剩下的遗留全指向同一个前置——第 4 期数据集要真实对话；
域泄漏值不值得修，取决于摘要在真实排障里有没有真掉链子（现在纯猜）；读话题历史值不值得
付"每周刷 token"的运维税，取决于真实群里有没有真失忆。所以是**先上量、让数据决定改哪个**，
而不是现在挑一个开工。

| 顺序 | 事项 | 状态 |
|---|---|---|
| 0 | 清理对账：删已合并分支、roadmap 对账、暂缓项写明判据、放弃项标状态 | ✅ 2026-08-03 完成。**唯一剩的是需内部知识的 2 处 `<待填>` 口语别名**，见第 3 期表格 |
| 0.5 | 修 trace 三处缺口（超时纳入失控信号 / 墙钟时间戳 / user_id） | ✅ change `fix-trace-triage-blindspots`（2026-08-03）。**它是第 2 步的前置**——修前 triage 对真实 trace 报 0 个候选 |
| 1 | **试点群攒量**（当前形态能做的上限） | 🔄 已接入飞书群，正在攒量（5 天 50 轮 / 12 session）。当前形态 = 开发机手起 `uvicorn --reload`、绑 127.0.0.1、状态全在本地 |
| 1.5 | **上 34 人生产群** | ⏸ **暂缓，与容器化同一道闸门**（2026-08-03 决定，见下方「部署形态」） |
| 2 | 第 4 期上半：真实 trace 跑 triage（零标注） | 🔄 前置已解除、通路已验证（真实 6 个文件跑出 3 个真候选、零误报），随流量持续做 |
| 3 | 第 4 期下半：oncall 数据集 + 门禁（要标注） | ⬜ 对话攒够再做 |

> **第 0.5 步为什么值得单独一行**：它揭示的是「**仪表瞎了比没仪表更危险**」。修前
> `triage scan` 对真实 trace 报 0 个候选，而真实群聊里明确发生过「连吃三次 60 秒超时、
> 白等 3 分钟」——最常见的真实故障恰好不可见，于是"0 个候选"被读成"一切正常"。
> 根因是同一句文案在 `agent_loop` 与 `trace_signals` 各写了一份，超时支从通用异常支
> 拆出去时把信号一起拆断了、且没有任何机制会提醒。**这是「沉默不是中立」的第三次出现**
> （前两次在工具层）。修完在真实数据上验证：0 → 3 个候选，全是那次真实坏 case，零误报。

### ⏸ 明确暂缓：部署形态与容器化（2026-08-03 用户决定）

**用户决定后面再做，先暂缓。** 记下来免得日后当成"忘了做"或"以为已经有了"。

**已查证的现状（零容器化，不是印象）**：全仓匹配 `dockerfile|docker-compose|.dockerignore|k8s|helm|*.yaml|*.yml` 只命中 OpenSpec 的 `.openspec.yaml` 元数据；README 第 349 行「支持 Docker 部署」在 **`### 生产化能力`**（待做清单）段下。实际运行形态是 README 第 294 行的
`uv run uvicorn app:app --host 127.0.0.1 --port 8000 --reload`。

三处与生产不兼容，**别在暂缓期间误以为"凑合能上"**：

1. **`--reload` 不能上生产**：它监听文件变化重启进程，而飞书长连接是进程内的——改一行代码就断连重连；且 reload 模式起的是 reloader + worker 两个进程，与第 1 期「硬约束单 worker」的前提不是一回事。
2. **绑 `127.0.0.1`**：不阻塞收飞书消息（长连接是 bot 主动连出去），但 Web 入口对外不可用。
3. **状态全在宿主机本地**：`data/smart_appointment.db`、`evals/traces/`、`repos/` 的 git mirror（OCS4 214M / OCS5 49M，运维预先 clone）。容器化时这三样都要挂卷。

**⚠ 连带效应：34 人上线与容器化是同一道闸门。** 不是"缺个 restart policy"，而是**还没有部署形态**——没有部署形态就没有进程守护，没有进程守护就会出现「进程半夜挂了没人重启没人知道、同事收到 ack 后永远等不到回复」。故第 1.5 步随之暂缓。**暂缓期间可做的是"试点"**（小范围、有人盯着、出事手动救），不是"上线"。

**动它之前要先定的四个决策**（没定就写不出能跑的 Dockerfile，只会得到个模板）：

1. SQLite 挂卷 还是 换 PostgreSQL
2. `repos/` 的 git mirror 放宿主挂进去 还是 打进镜像（体积 260M+）
3. 飞书长连接的单实例约束怎么在编排层表达（replicas 必须锁 1，多副本会重复消费且进程内去重表拦不住）
4. `.env` 里的凭据怎么注入（当前是宿主机文件）

**恢复的触发条件**：要把 bot 交给 34 人用时。届时起一个 change 一并做掉：上述四个决策 + Dockerfile/compose + 进程守护（`Restart=always`）+ **crash 后在途任务不静默**（启动时扫 DB 里"有 user 回合但无配对 assistant 回合"的会话，补一句"上次处理中断了，请重发"——第 1 期已有「历史成对」不变量与补写兜底回合的机制，接上去即可）。

**条件触发，不预先排期**（现在动大概率白干）：

- **记忆层三处域泄漏**（[tests/test_domain_loading.py](../tests/test_domain_loading.py) 的
  `_KNOWN_DOMAIN_LEAKS` 白名单守着）：**正解取决于预约域是否退役**。若退役，正解从"给 `Domain`
  加配置槽位让文本随域可配"退化成"直接把字符串换成值守域的",工作量差一个量级。且退役预约域时
  顺手解掉比两次分别做便宜——**故不要单独立项修它**。
- **读 Lark 话题历史**：等第 3 期表格里写的触发判据。
- **预约域退役**：本身没有任何 change。它还在跑（缺省域、51 条冻结用例、
  `services/recommendation_service.py` 一个未实现的 TODO、以及上述域泄漏的另一端）。
  "要退役"目前是个判断、不是个计划——立项时把域泄漏一起带掉。
- **任务持久化**：不要预防性地做。等第 1 步上量后，若"丢在途任务"真开始咬人再提前。
  ⚠ 但注意与上面「部署形态」的区别：**任务持久化**（crash 后任务本身还在、能续跑）是可选优化；
  **crash 后不静默**（至少告诉用户"中断了，请重发"）是 34 人上线的必要项，已并入部署形态那个 change。
  别把这两件混成一件而以为都可以拖。
