## Context

参考实现 `probe.py`（381 行）是一个**自包含 CLI**：argparse 取参、`urllib.request` 发请求、单行 JSON 打 stdout，由 opencode 的 worker 用 `python3 probe.py ...` 调起。它在参考系统里工作得很好，因为那边 AI 跑在子进程里、天然有 shell 与文件系统。

本项目不是那个形态：工具是进程内的 async handler，模型拿到的是 handler 的返回值。所以这不是"把文件拷过来"，而是**把能力从 CLI 形态翻译成 service + tool 形态**。翻译过程中有四处必须改，其余照搬。

同时移植的还有那套**排查知识**——`vlog-query` 的 SKILL.md（150 行查询经验）与 4 份 reference（约 97KB）。路线图说它"比代码更值钱"，我同意：LogsQL 怎么写才走索引、告警时间是北京而绝对窗是 UTC、告警晚于事件要往前放宽窗口……这些都是真实事故换来的，重写代码容易，重新踩坑很贵。

## Goals / Non-Goals

**Goals:**
- oncall 域能装载、能查日志、能按需读排查知识；`AGENT_DOMAIN=oncall` 一切即换域。
- 把参考系统的查询经验**带过来且带对地方**——它的读者是模型，所以该进 prompt/description 的进 prompt，该按需加载的按需加载。
- 只读红线由权限策略硬 enforce，不靠 prompt 自觉。
- 第 2 期的领域包契约在此第一次受检：**装 oncall 域不该需要改 `harness/` 一行**。

**Non-Goals:**
- 不做 `repo` / `docs_search`（切片 2、3）。
- 不建 oncall 评估集（第 4 期）。
- 不实现参考系统的"落盘 + python 筛"手法——本项目没有给模型的文件系统沙盒，改用别的办法控上下文（见 D5）。
- 不移植 `daemon.py` / `larkbot.py`（IM 接入第 1 期已用自己的实现做完）。

## Decisions

### D1 async httpx，不是 `urllib.request`

`probe.py` 用 `urllib.request` —— **同步阻塞**。直接搬进 async handler，就是第三次重演同一个缺陷：

| 次序 | 缺陷位置 | 修复 change |
|---|---|---|
| 1 | 知识库检索 → `embed_query` | `fix-embedding-timeout-blocking`（2026-07-30） |
| 2 | 技师专长匹配 → `embed_input` | `fix-technician-embedding-blocking`（2026-08-02） |
| 3 | ← **就是这里，如果照搬** | — |

日志查询比前两者更危险：`probe.py` 的 timeout 默认 **60 秒**，且"发现模式"会**并发探所有 env**（4 个租户去重后 3 个）。同步实现下，一次查询能把事件循环冻住一分钟——飞书长连接的心跳全停。

故 `services/vlog.py` 用 `httpx.AsyncClient`，显式秒级超时（沿用 `EMBEDDING_TIMEOUT_SECONDS` 那套口径，新增 `VM_LOGS_TIMEOUT_SECONDS`，缺省 60——日志查询确实慢，但**上限必须是显式的**，不能落到客户端默认）。多 env 探查用 `asyncio.gather` 并发，与技师匹配那次同一形状。

配套一条"心跳不停"回归测试，范式沿用 `tests/test_technician_matching_nonblocking.py`（含 `@pytest.mark.timeout`——循环冻住时 asyncio 超时救不了自己）。

### D2 CLI 的三种入参模式原样保留，但收进一个工具

`probe.py` 有三种互斥入口：`--term`（裸词发现）/ `--logsql`（自拼精确查）/ `--url`（vmui URL 解析）。**不拆成三个工具**——它们是同一件事（查日志）的三种给法，拆开会让模型面对三个高度相似的工具、选择困难；合成一个工具、用互斥参数表达，schema 层就能校验"恰好给一个"。

```
vlog_query(term?: list[str], logsql?: str, url?: str,
           env?: "prod"|"uat"|"dev"|"stg", window?: str,
           start?: str, end?: str, limit?: int, fields?: list[str])
```

Pydantic model validator 强制三者恰好给一个（与 evals 用例 `input` / `turns` 互斥同款做法）。

### D3 查询经验分三处安放，按"谁读它"决定

参考系统把 150 行经验放在 SKILL.md 里给 worker 读。本项目没有 skill 机制（`remove-skills-skeleton` 已按 YAGNI 移除），且这些经验的读者不同、时机不同，硬塞一处会互相稀释：

| 知识 | 放哪 | 为什么 |
|---|---|---|
| "多词用引号精确 AND、别上 `~` 正则"、"时间窗是头号杠杆"、"领头放最稀有的词" | **工具 description** | 模型**构造入参那一刻**要看到；description 就是给模型的说明书 |
| "告警时间是北京、绝对 `start/end` 是 UTC、告警晚于事件要往前放宽" | **工具 description**（时间参数处） | 同上，且这是最容易错的一处 |
| 值守人设、只读红线、"0 命中/失败怎么如实回复、绝不武断归因 VPN" | **`prompt.py`** | 跨工具的行为策略，不属某个工具 |
| 4 份 reference（97KB）+ 那张 20 行路由表 | 路由表进 **prompt**、本体经 **`load_reference` 工具**按需读 | 97KB 全塞上下文既贵又稀释注意力；参考系统也正是这么做的 |

`load_reference` 是本切片的第二个工具：入参是枚举（4 个 reference 名），返回文件内容。**枚举而非自由路径**——自由路径等于给模型一个任意文件读取工具，是权限漏洞。

### D4 只读红线：策略硬 enforce，且不止于"没有写工具"

`domains/oncall/policy.py` 的策略：**任何 `dangerous=True` 的工具一律拒绝**，附理由"值守域只读，不执行任何写操作"。

本期注册的两个工具都是 `dangerous=False`，所以这条策略当前**不会拒任何东西**——那正是要点：它是**防线而不是开关**。将来谁往 oncall 域加了个写工具（改配置、重启服务、提 PR），策略会在分发前拦下，而不是等 code review 发现。路线图的设计判断 6 写得很清楚："红线靠 `permission.py` 硬 enforce，不靠 prompt 自觉"。

第 2 期已经把 policy 接进了 `ToolRegistry`（那期特意通的管子），本期是它第一个**真正有约束力**的使用者。

### D5 结果规模：截行数，绝不截 `_msg`

参考系统靠"落盘 + `python -c` 筛"控上下文，本项目没有给模型的文件系统，得另想办法。

**做法**：`limit` 在 schema 层封顶（`le=200`，缺省 20），返回结构化 `lines`；**每条 `_msg` 完整返回、绝不截断**。

这个不对称是有依据的——SKILL.md 明确警告："关键行打完整 `_msg`、绝不 `m[:N]` 截断——堆栈定位、入参/出参 JSON 都在 `_msg` 靠后，截断就把根因丢了"。截断一条日志的尾巴，等于把根因扔了；少返回几条日志，模型还能收窄条件再查。

**同时必须把 `hits`（总命中数）与 `len(lines)`（实际返回）分开呈现**。参考系统有过真实事故：单词命中 7205 条、`--limit` 截断后本地筛第二个词得到 0 条，误判"没有"。工具返回里两个数字都在，且 description 明说"`hits` 是总数、`lines` 只是样本"。

### D6 凭据只在 service 层，且错误信息不得回带

`VM_LOGS_URL` / `VM_LOGS_USER` / `VM_LOGS_PASSWORD` 由 `config/` 读取、`services/vlog.py` 用于构造 Basic Auth header。**工具入参里没有任何凭据字段**，模型无从看见也无从传。

一个容易漏的点：**失败时的错误信息可能回带凭据**——`urllib`/`httpx` 的异常字符串常含完整 URL，而 `VM_LOGS_URL` 若是 `https://user:pass@host` 形式就泄了。故 service 层在把异常转成结果前 MUST 做一次脱敏（只保留 host、丢弃 userinfo 与 query）。参考实现没这层，因为它的输出只进 worker 的 stdout；本项目的错误串会被回灌进 LLM 上下文，再随回复发到飞书群里——**风险等级不同，不能照抄**。

### D7 错误分类原样移植，且"不武断归因"写进 spec

`_classify_err` 的四分类（`timeout` / `connect_failed` / `http_error` / `other`）与 `_regex_hint`（超时且含 `~` 时提示改引号精确 AND）**原样移植**——它们是踩过坑的产物（"72h/24h/6h 窗连超 3 次、累计浪费 300+ 秒顶穿总超时"）。

更要紧的是把 SKILL 里那条行为约束写成需求：**查询失败时 MUST 如实转达（查了什么 + 原始错误 + 分类 + vmui 链接），MUST NOT 武断断定是 VPN**。这不是措辞讲究——值守场景里"是不是 VPN 断了"是用户才能判断的事，bot 替他下结论会把排查带偏。

### D8 vmui URL 逐字透传，不重拼

每条结果带 `vmui_url`（可点开 UI 深挖）。SKILL 里有一整段警告：**必须逐字复制，绝不自己拼/改/缩**——别根据 env 编域名、别把 traceId 直接当 query 塞进去（真实的 query 是 urlencode 后的 LogsQL）。

对应到本项目：`vmui_url` 由 service 生成并原样放进工具返回值，工具层不加工；且在 description 里明写"转给用户时逐字复制"。

## Risks / Trade-offs

- **[无法端到端验证]** 查真日志需内网 + 凭据，CI 里做不到。→ 缓解：离线测试覆盖"请求构造正确、异步不阻塞、失败分类正确、URL 往返一致"；**"查得对不对"标记为需真实凭据手动冒烟**，验收结论如实区分二者，不含糊成"测试全绿"。
- **[reference 会漂移]** 服务 profile 是快照，机器/分区会变。→ 缓解：把 SKILL 里那条"环境漂移：被动触发、绝不主动验证"的策略一并移植进 prompt——只在按 profile 查却 0 命中、或用户提到 profile 里没有的东西时才回问，**绝不为"防漂移"主动跑 VL 核对**。
- **[97KB reference 进仓库]** 增大仓库体积，且内容是公司内部知识。→ 取舍：它是本期的核心价值，不带过来这个域就只有一个空壳工具。体积上 97KB 可忽略。
- **[领域包契约可能不够用]** 第 2 期的五槽位是照预约域抽的，oncall 域可能需要第六样（如 reference 目录）。→ 这正是本期要检验的。**若真需要扩，改 `Domain` 加槽位是对的；若需要改 `harness/` 才装得下，说明抽象漏了，回头修抽象而不是打补丁。**
- **[记忆层的域泄漏会在 oncall 域显形]** 第 2 期记账的三处（`summary_schema.py` 的按摩例子等）在 oncall 域跑起来就会把"技师姓名"之类塞进摘要提示。→ 本期仍不修（那是独立改造），但**若冒烟时发现摘要明显被带偏，应提前处理**——把观察写进 tasks 收尾。

## Migration Plan

1. `services/vlog.py` + 离线单测（此时无工具、无域，纯 service）。
2. `domains/oncall/` 骨架：prompt / policy / 空 tools，注册进 `_DOMAINS`，装载测试绿。
3. `vlog_query` + `load_reference` 两个工具接上，域装载后 registry 里能看到。
4. reference 4 份文件与路由表落位。
5. 真实凭据手动冒烟（需内网），结论如实记录。

**回滚**：单分支 revert；oncall 域不注册即完全不影响预约域（缺省仍是 appointment）。

## Open Questions

- reference 文件放 `domains/oncall/references/` 还是 `domains/oncall/knowledge/`——实现时定，倾向前者（与参考系统同名，便于对照）。
- 第 4 期建 oncall 评估集时，`load_reference` 的调用要不要计入工具调用指标——留到那时再定。
