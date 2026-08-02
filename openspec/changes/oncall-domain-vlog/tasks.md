> **移植纪律**：`probe.py` 是参考实现，不是要拷贝的源文件。**语义照搬、形态重写**——
> 保留它踩坑换来的东西（env→租户映射、两种模式、错误四分类、正则超时提示、vmui URL 往返），
> 但传输层换 async httpx、输出形态换成 service 返回值。**照搬 `urllib` 即第三次重演阻塞缺陷。**

## 1. services/vlog.py（先纯 service，无工具无域）

- [x] 1.1 `config/` 新增 vlog 凭据读取：`VM_LOGS_URL` / `VM_LOGS_USER` / `VM_LOGS_PASSWORD` + `VM_LOGS_TIMEOUT_SECONDS`（缺省 60，**显式秒级、不落客户端默认**）。沿用 `resolve_embedding_timeout` 那套「显式参数 > 环境变量 > 缺省」的口径。同步补 `.env.example`。
- [x] 1.2 传输层：`httpx.AsyncClient` + 显式 timeout + Basic Auth header。**代理绕行**照搬（内网 host 走不通公司外网代理，`probe.py` 的做法是清空 `*_PROXY` 并设 `no_proxy=*`；httpx 用 `trust_env=False` 更干净——两种都行，选后者并注释说明等价性）。
- [x] 1.3 环境映射与目标解析：`ACCT = {prod:3, uat:2, dev:0, stg:0}`、别名 `prd→prod`、未指定 env 时**按租户去重后并发探查**（`asyncio.gather`，不是串行 for）。
- [x] 1.4 两种查询模式：**发现模式**（把窗口写进查询语句的 `_time:` 而非 HTTP start/end——`probe.py` 注释记了这个坑：该 VL 的 `/hits` 不按 HTTP 时间过滤，只有查询内的 `_time` 对两个端点都生效，否则会出现「/hits 报命中、/query 却 0 行」的口径不一致）；**精确窗模式**（给了 start 即直接 query）。
- [x] 1.5 vmui URL 解析与生成：参数在 fragment（`#/?query=...`），含相对时间映射表；生成的 URL 原样透传，**工具层不得加工**。写一条往返测试（解析→生成→再解析，语义一致）。
- [x] 1.6 错误四分类原样移植：`timeout` / `connect_failed` / `http_error` / `other`；正则超时提示（查询含 `~` 且超时 → 建议改引号精确 AND）一并移植。
- [x] 1.7 **凭据脱敏**（参考实现没有这层，本项目必须有）：异常信息里的连接地址 MUST 去掉 userinfo 与 query 再返回。理由是错误串会回灌进 LLM 上下文、并可能随回复发进飞书群——与参考系统只打到 worker stdout 的风险等级不同。
- [x] 1.8 离线单测（注入 fake transport，**绝不触网**）：两种模式的请求构造、env 映射与去重、URL 往返、四种错误分类、正则提示、脱敏（构造一个 `https://u:p@host/...` 的异常，断言返回串里没有 `u` 和 `p`）。
- [x] 1.9 **「心跳不停」回归测试**：注入永不返回的 fake transport，断言查询挂起期间心跳协程跑满；必须带 `@pytest.mark.timeout`（循环冻住时基于 asyncio 的超时救不了自己）。并断言多 env 是并发而非串行（并发峰值 = env 数）。

## 2. domains/oncall/ 骨架

- [x] 2.1 建包：`prompt.py` / `policy.py` / `tools/`（暂空）/ `references/`（暂空）/ `evals/`（空目录，第 4 期填）+ `build_domain()`。
- [x] 2.2 `policy.py`：拒绝一切 `dangerous=True`，理由写"值守域只读，不执行任何写操作"。**注意这是防线不是开关**——当前两个工具都是只读，故它不会拒任何东西；写测试时要**专门造一个 dangerous 工具**验证它真的拦得住，否则这条策略等于没测。
- [x] 2.3 `prompt.py`：值守人设 + 只读红线 + 「0 命中/查询失败怎么如实回复、**绝不武断归因 VPN**」+ 「环境漂移被动触发、绝不为防漂移主动跑 VL 核对」+ reference 路由表（20 行，从参考系统的 `references/README.md` 移植）。
- [x] 2.4 注册进 `domains/_DOMAINS`；`AGENT_DOMAIN=oncall` 装载测试绿（五槽位齐全、切换生效）。
- [x] 2.5 ⚠ **检验第 2 期的抽象**：装 oncall 域**不该需要改 `harness/` 一行**。若发现必须改，停下——那说明第 2 期的领域包契约漏了东西，正确做法是回头补 `Domain`（如加一个 references 槽位），**不是**在这里打补丁绕过。把结论记进第 5 组。

## 3. 两个工具

- [x] 3.1 `vlog_query`：薄封装 service，`dangerous=False`。入参 `term` / `logsql` / `url` **三者恰好给一个**（Pydantic model validator，与 evals 用例 `input`/`turns` 互斥同款），外加 `env` / `window` / `start` / `end` / `limit`（`le=200`，缺省 20）/ `fields`。
- [x] 3.2 `vlog_query` 的 **description 是本切片的关键交付物之一**——它是模型构造查询时唯一会读的东西。必须写进去：① 多词优先引号精确 AND、**别上 `~` 正则**（真实事故：72h/24h/6h 连超 3 次、浪费 300+ 秒顶穿总超时）；② 时间窗是头号杠杆、领头放最稀有的词；③ **告警时间是北京、`_time` 显示也是北京（直接对齐不换算），但绝对 `start`/`end` 按 UTC（北京 −8h），更稳的做法是用相对 `window`**；④ 告警晚于事件（数十秒~数分钟），窗口要**往告警时刻之前放宽至少 10~30 分钟**，绝不只查告警那一分钟；⑤ `hits` 是总数、`lines` 只是样本；⑥ `vmui_url` 转给用户时**逐字复制，绝不自己拼**。
- [x] 3.3 `load_reference`：入参是**受限枚举**（4 个 reference 名），返回文件内容。**绝不接受自由路径**——那等于给模型任意文件读取能力。
- [x] 3.4 两个工具进 `domains/oncall/tools/__init__.py` 的 `TOOLS`；域装载后 registry 里能查到、schema 导得出。
- [x] 3.5 结果规模：`limit` schema 封顶；**单条 `_msg` 完整返回、绝不截断**（SKILL 明确警告：堆栈与入参 JSON 都在正文靠后，截断即丢根因）。写测试守住"截条数不截正文"。

## 4. 排查知识移植

- [x] 4.1 移植 4 份 reference 到 `domains/oncall/references/`：`ocs-service-profiles.md`(26KB) / `mt-returncode.md`(19KB) / `ocs4-returncode.md`(23KB) / `ocs5-returncode.md`(29KB)。**内容一字不改**（它们是别处维护的知识快照，本仓只是使用方）。
- [x] 4.2 路由表（`references/README.md` 那 20 行表）移植进 `prompt.py`——它是**给模型的分诊表**，必须在上下文里；reference 本体不进。
- [x] 4.3 把 SKILL 里那条**「清单/环境元信息类问题直接用 profile 回答、不要查 VL」**写进 prompt——这是明确的红线（"绝不为验证 profile 有没有漂移而主动跑 VL"），也是省时间的关键分诊。
- [x] 4.4 `load_reference` 的枚举与实际文件对齐；加一条测试：枚举里每个名字都能读到文件（防止改名后运行期才炸）。

## 5. 验证与收尾

- [x] 5.1 `uv run pytest` 全绿；**通过数差额逐条说清**（新增 service 测试 + 域装载 + 工具 + 知识路由）。
- [x] 5.2 装载冒烟：`AGENT_DOMAIN=oncall` 起服务，registry 里有 `vlog_query` / `load_reference` 且**没有**预约域的工具；`AGENT_DOMAIN` 不设时仍是预约域、行为不变。
- [ ] 5.3 ⚠ **真实凭据手动冒烟**（需内网）——**未做，挂起等环境**。CI 与本地都没有 VM_LOGS_* 凭据与内网可达性。**在此之前不得声称日志查询已可用。**
- [x] 5.4 ⚠ **验收表述要诚实**：离线测试证明的是「请求构造正确、异步不阻塞、失败分类正确、URL 往返一致」；**「查得对不对」只有 5.3 能证明**。收尾结论 MUST 分开写这两件事，不得含糊成"测试全绿即可用"。
- [x] 5.5 记录第 2 期抽象的检验结论（见 2.5）：装 oncall 域是否真的没碰 `harness/`；若加了 `Domain` 槽位，说明加了什么、为什么。
- [x] 5.6 记忆层域泄漏在 oncall 域的观察：**结构性存在已确认**——`ConversationSummary` 的 Field description 举的仍是「技师姓名」「只要女技师」，值守会话的摘要会带着这些例子去归纳；`long_term.py` 的 `_TYPE_LABELS` 同理。**但实际影响未测**：那需要真实 LLM 跑一段多轮值守对话再看摘要质量，本切片没有这个条件（与 5.3 同因）。故**不据此判断严重程度**，维持第 2 期的处置（白名单记账、留独立改造），待真实对话跑起来后再评估。
- [x] 5.7 更新 `docs/oncall-bot-roadmap.md`：第 3 期标注切片 1 完成、切片 2/3 待做。


## 6. 实现期的计划外发现（如实记账）

- [x] 6.1 ★ **冒烟发现第 2 期的一处遗留缺陷**：`api/chat_handler` 把「主 registry 只放 delegate」写死了，那其实是**预约域的结构**、不是运行时不变量。装上无子 Agent 的值守域 → 主 Agent 只有一个 `delegate` 却无处可派，**域的两个工具够不着、且不报错**（静默失能，比报错糟）。修法：新增 `domains.build_main_registry(domain, delegate_factory)`，按 `len(domain.subagents)` 决定形状——有子 Agent 走 delegate、无子 Agent 直接放工具。**判的是结构属性不是域名**，故「运行时对域无知」的约束不破。`evals/agent_capture.py` 的同款装配一并改（两处装配必须同源，否则会漂）。补 3 条回归测试。
- [x] 6.2 **值守域刻意不设子 Agent**，与预约域不同：值守的主动作（查日志 → 下钻 → 定位）是一条连贯推理链，下钻要用上一步命中日志里的 pod_ip / traceId；拆成子 Agent 得靠汇总文本传中间态、必丢细节。强行包一个「持有全部工具」的子 Agent 是纯开销（多一层 LLM 循环、多一次上下文拷贝，换不来隔离收益）。切片 2、3 加入代码分析与文档检索后再评估是否出现真正的分工。
- [x] 6.3 **第 2 期抽象的实检结论**：装一个全新的域（工具集完全不同、无子 Agent、策略非 allow_all）**没有改 `harness/` 一行**，`Domain` 的五槽位够用、没加新槽位。改动只落在 `api/` 与 `evals/` 的**装配点**（6.1），那是装配约定的问题、不是抽象的问题。领域包契约成立。
