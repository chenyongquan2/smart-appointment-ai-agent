# OCS 服务日志知识库（ocs-service-profiles）

> **这是 bot 的 OCS 排查记忆**：worker 按 `references/README.md` 路由索引命中信号后读本文件，用来把**非技术人员的自然语言**（"stg 的 ocs4 在报错"）映射成**正确的查询条件 + 该服务的根因定位手法**。
>
> **worker 怎么用**（见 vlog-query/SKILL.md）：① 从用户话里按「别名/口语」认出是哪个服务 + 哪个 env（+ 分区/部署方式，如说了）→ ② 按「定位字段」拼 `probe.py` 的 `--env`（租户）+ `--logsql`（字段过滤）→ ③ 用「常用关键词」python 筛 → ④ 照「日志格式 / 根因线索」分析（**别套错语言的栈格式**）。
>
> **查询拼法约定**：
> - `probe.py --env`（prod/uat/dev/stg）决定**租户 accountID**（固定 prod=3 / uat=2 / dev=stg=0）。PRD/UAT 的 cpp 与此一致（3 / 2），正常查。**⚠️ cpp(OCS) 的 STG 租户其实是 1（≠ probe 固定的 0），且 probe 暂无按租户覆盖的入口 → cpp STG 当前无法直接查、查询通路待定**（见各服务 STG 段；定位字段已确认，待机制定了即可用）。
> - **定位字段**（project / host / env / file 等）拼进 **LogsQL**：`project:CPP host:cpp-mix-s2 env:STG`。值含空格/特殊字符用引号；`file` 路径含 `:\` 很脆，优先用 `host`+`project`+`env` 圈定，必要时再用 `file:"*20-rotation.log*"` 这类子串。
> - 同一 env 可能有**多机器 / 多分区 / 多部署方式**——用户没说具体哪台就**先按该服务该 env 的所有 host 并列查**，或回问用户是哪个分区。
>
> **时间与时区（重要 · 全服务通用，换算别搞错）**：涉及**三个时区**——
> ① VL 第一列 `_time` = **北京时区（UTC+8）**；
> ② 日志**正文里的时间戳** = **OCS 所在服务器的时区**（按该机配置定，不一定是北京；**各机偏移差异很大**：OCS4 PRD 正文比 VL 早约 8h（机器≈UTC）、OCS5 PRD 正文≈VL（≈北京）、**OCS5 UAT/STG 机器 = UTC-8 且启用夏令时（实际 UTC-7），对北京(UTC+8) 差 15h，故正文比 VL 早约 15h** ⇒ **务必逐机确认、绝不套用同一偏移；夏令时还会随季节切换**）；
> ③ 日志里 **MT 侧的时间** = **MT 服务器自己的时区**（有冬令时/夏令时切换）。
> 排时间线、跨上下游对齐时这三者要分清、按需换算，**别直接拿不同来源的时间相减/比较**。给用户的结论里注明用的是哪个时区。
> **查询时间窗的坑**：VL 后端按 **UTC** 解析绝对时间（probe `--start/--end` 传 UTC）；而告警/正文(PRD)是北京/UTC 各异 → 用绝对窗前先换算到 UTC，或**改用相对 `--window`** 从现在回看更稳。**告警晚于事件**，窗口要往告警时刻之前放宽（详见 SKILL.md「按告警排查」）。
>
> **MT 维护 / 重启窗口（判断 MT 断连/异常是否"例行"的重要参照 · 均北京时间）**：
> - **工作日例行维护重启**：夏令时约 **05:00~05:30**；冬令时顺延一小时（约 **06:00~06:30**）。
> - **周末**：CFD 周六日休盘、数字货币不休盘；**13:00~14:00 休盘时段 MT 维护会重启**。
> - **其他时间的非计划重启**：MT 可用内存过低 / 订单量大 / 延迟高 时可能重启；**MT5 的 access server 也可能紧急重启**。
> - **用法**：分析 MT 断连（`OnDisconnect`）/ 超时 / 连不上时，**先看事件时间（北京）是否落在上述窗口**——落窗口内多为**例行维护重启**（如实告知、通常非事故，仍建议确认 MT 侧）；不在窗口则按**非计划重启 / 网络问题**排查（查对应 MT server 侧）。
>
> **维护规则**：
> - 标 `<待填>` / `<待补充>` / `⚠️待确认` 的 = **未确认知识**，worker **不得当真**：照通用流程查、在 reply 里提示"该项 profile 待补充"，**绝不编字段/关键词**。
> - 字段名 / 过滤值请填**真实可用**的（worker 原样拼进查询）；改这里不动 SKILL.md / probe.py。
> - **清单 / 环境元信息类问题**（"列出/有哪些机器·服务·环境·分区"、"X 部署在哪"）→ **worker 直接据本 profile 的表作答、不查 VL**（profile 是环境清单的权威来源；查 VL 慢且因窗口/limit 不全而漏判）。
> - **环境会变（机器/分区/部署/租户可能调整）· 漂移检测被动触发、绝不主动验证**：本 profile 是某时刻的快照。**仅当**遇**漂移信号**（**确实在查日志且按 profile 的 host/分区查却 0 命中**、用户提到这里没有的机器/分区/环境、或用户直说"机器/环境换了"）→ **别硬查/瞎猜**，在 reply 里**向用户确认是否环境有变**（具体哪台/哪分区/改了什么）、并说明"确认后会更新本知识库"。**绝不为"防漂移"对清单类问题主动跑 VL 核对。****worker 只读本文件、不能改它**；实际更新由维护者用 Claude Code 改 `ocs-service-profiles.md`（填进确认后的新机器/分区/租户）+ 提交——下个 worker 即用上新记忆。

---

## ocs4（ocs-v4.* 版本）

- **别名 / 口语叫法**：`OCS4` / `ocs-v4` / `ocs4`
- **语言**：C++
- **作用简述**：交易系统中间层——接收上游请求（`message_type`：`trading_system` 或 `CRM`；`cmd` 如 `get_history_deal` / `select_account`），经 TaskCoordinator 调度 + Redis 请求去重，**按 cmd 路由到 MT4（`CMT4Processor`，`src\ocs\MT4`）或 MT5（`CMT5Processor`，`src\ocs\MT5`）** 处理后回 response。每个请求有端到端 `request_id`。
- **两种部署方式（影响日志路径）**：
  - **手动部署（Windows 服务）**：日志在 `C:/saas-cpp\ocs\<分区目录>\RunLog\*.log`（如 `trading-system-a-4.0\RunLog\20-rotation.log`）。
  - **Nomad 部署**：日志在 `C:/ProgramData\HashiCorp\nomad\data\alloc\<allocid>\alloc\build\windows\x64\release\RunLog\20-rotation.log`。
  - 共同点：文件名都以 **`RunLog\20-rotation.log`** 结尾（`file:"*20-rotation.log*"` 可跨部署粗筛）。
- **`project` 标签按 env 而定（⚠️ 不是按部署方式，别套规律）**：STG 手动=`CPP`、UAT(C分区/Nomad)=`minirps`、STG B分区=待补充；**PRD(Nomad) 有两类**：`private-bss-rocket-cpp`（主体 Rocket、DFID）/ `private-bss-ocean-cpp`（主体 Ocean(CG-Trade)、RKX、6i）。
- **主体（品牌）维度（PRD）**：OCS4 PRD 按主体分多台机器，**主体由 `host` 区分**（host 名含主体缩写：`cg`/`rkx`/`6i`/`p11`(DFID)/`pX`(Rocket)）；`project` 只粗分上述两类、**不唯一对应主体** → **定位某主体优先用 `host`**。
- **主定位字段** = `project` + `env` + `host`（这三个足够圈到日志）。
- **分区有两种，别混**：① **业务字母分区 `A/B/C/D/E/G`** = 请求 JSON 的 `request_zone`，**按 `message_type`(CRM / TS) + 分区** 对应到具体 host（见 OCS4 PRD「Rocket 各机分区表」）——这才是用户口里的"X 分区"。② VL 的**数值 `partition` 字段**（0~4，含义未确认、与字母分区不对应）**少用**，默认不碰。
- **`offset`** 是日志字节偏移、**不用于过滤**，忽略。

### 各环境 × 分区 × 机器（定位字段）

**STG**（⚠️ **查询通路待定**：cpp STG 租户=1，但 probe 固定 `stg=0` 且无租户覆盖入口 → 当前无法通过 probe 直接查；VL UI 已可正常查，下表 host/project 定位字段已确认）

| 分区 | host | 部署方式 | LogsQL 定位（字段已确认） | file（参考） |
|------|------|---------|------------------------------|--------------|
| A分区 | `cpp-mix-s2` | 手动（CRM + TS A分区） | `project:CPP host:cpp-mix-s2 env:STG` | `C:/saas-cpp\ocs\trading-system-a-4.0\RunLog\20-rotation.log` |
| B分区 | `cpp-mix-s1` | Nomad（CRM + TS B分区） | `project:minirps host:cpp-mix-s1 env:STG` | Nomad alloc 路径，`RunLog\20-rotation.log`（2026-06-12 确认：VL 已正常采集，vmui 可查） |

**UAT**（`--env uat`，租户 accountID=2）

| 分区 | host | 部署方式 | LogsQL 定位 | file（参考） |
|------|------|---------|-------------|--------------|
| C分区 | `trade-cpp-u2` | Nomad | `project:minirps host:trade-cpp-u2 env:UAT` | `C:/ProgramData\HashiCorp\nomad\data\alloc\**\*.log` |

**PRD**（`--env prd`，租户 accountID=3）— 全 Nomad，按**主体（品牌）** 分机器。**定位某主体优先用 `host`**（见下）。`host:<host>` 已能唯一锁一台。

| 主体 | host | project | partition |
|------|------|---------|-----------|
| Rocket | `prd-bss-rocket-cpp-p1` | private-bss-rocket-cpp | 0 |
| Rocket | `trade-cpp-p2` | private-bss-rocket-cpp | 2 |
| Rocket | `trade-cpp-p3` | private-bss-rocket-cpp | 4 |
| Rocket | `trade-cpp-p9` | private-bss-rocket-cpp | 0 |
| Rocket | `trade-cpp-pe` | private-bss-rocket-cpp | 2 |
| Rocket | `trade-cpp-pf` | private-bss-rocket-cpp | 3 |
| Rocket | `trade-cpp-pg` | private-bss-rocket-cpp | 2 |
| Rocket | `trade-cpp-ph` | private-bss-rocket-cpp | 1 |
| DFID | `trade-cpp-p11` | private-bss-rocket-cpp | 4 |
| Ocean (CG-Trade) | `trade-cpp-cg-p1` | private-bss-ocean-cpp | 1 |
| RKX | `trade-cpp-rkx-p1` | private-bss-ocean-cpp | 5 |
| 6i | `trade-cpp-6i-p1` | private-bss-ocean-cpp | 0 |

> **主体别名**：Ocean = CG-Trade。
> **定位逻辑**：① 用户点名主体（Rocket / DFID / Ocean / CG-Trade / RKX / 6i）→ 用该主体对应 `host` 查（`env:PRD host:<host>`）；多台的主体（Rocket）按那几台 host 列举或 OR。② `project` 只能粗分：`private-bss-rocket-cpp`（含 Rocket+**DFID**）、`private-bss-ocean-cpp`（含 Ocean+RKX+6i）——**不能仅凭 project 区分同组内主体**（如 Rocket vs DFID 都在 rocket-cpp，要靠 host）。③ 没点名主体/机器 → 全 `env:PRD` 查 request_id，再看命中 host 反推主体；或回问哪个主体。
> Nomad 日志路径形如 `D:/ProgramData\HashiCorp\nomad\data\alloc\<allocid>\alloc\build\windows\x64\release\RunLog\20-rotation.log`（盘符 C:/D: 视机器）。
**各机 → CRM/TS 字母分区**（字母分区 = 请求 JSON 的 `request_zone`；用户说"X 分区"→ 先按 **主体 + `message_type`(CRM/TS)** 在此表找到对应 host 再查）：

| 主体 | host | CRM 分区 | TS(trading_system) 分区 | 数值 partition |
|------|------|---------|------------------------|----------------|
| Rocket | `prd-bss-rocket-cpp-p1` | A | 待补充 | 0 |
| Rocket | `trade-cpp-p2` | — | A | 2 |
| Rocket | `trade-cpp-p3` | B | B | 4 |
| Rocket | `trade-cpp-p9` | C | — | 0 |
| Rocket | `trade-cpp-pe` | D | — | 2 |
| Rocket | `trade-cpp-pf` | — | D | 3 |
| Rocket | `trade-cpp-pg` | E | — | 2 |
| Rocket | `trade-cpp-ph` | G | G | 1 |
| DFID | `trade-cpp-p11` | F | F | 4 |
| Ocean (CG-Trade) | `trade-cpp-cg-p1` | B | B | 1 |
| RKX | `trade-cpp-rkx-p1` | D | D | 5 |
| 6i | `trade-cpp-6i-p1` | A | A | 0 |

> ⚠️ **字母分区跨主体重复、非全局唯一**：同一字母在不同主体都可能有——B 分区：Rocket=`trade-cpp-p3` / Ocean=`trade-cpp-cg-p1`；A 分区：Rocket=`trade-cpp-p2`(TS)·`p1`(CRM) / 6i=`trade-cpp-6i-p1`；D 分区：Rocket(`pe`/`pf`) / RKX=`trade-cpp-rkx-p1`。→ **用户说"X 分区"必须先定是哪个主体**（按主体/project + 分区 + message_type 锁 host；host 名本身已唯一）。
> 注：**Rocket 的 D 分区按服务拆两台**（CRM D 在 `trade-cpp-pe`、TS D 在 `trade-cpp-pf`，pf 仅 TS）；其余主体（DFID/Ocean/RKX/6i）均单机、CRM 与 TS 同分区同机。
> ⚠️ 仅剩 Rocket `prd-bss-rocket-cpp-p1` 的 TS 分区待补充。

### 主搜索键 = request_id（首选）
- `request_id` 是端到端 32 位 hex（如 `4e618c02505546d496c44a15e2de0997`，无连字符）。日志里有 `request_id:`、`requestId:` 两种拼写 + 裸串出现 → **直接 `probe.py --term "<request_id>"` 全文搜最稳**，一次捞齐该请求所有行。**用户甩来一串 32 位 hex 默认就是 request_id。**
- 拉齐后**按行内时间 `[YYYY-MM-DD HH:MM:SS.mmm]` 排序**（不是 VL `_time`）重建时间线。

### 常用关键词（python 筛用）
- **报错/异常类**：失败行级别常为 `[warning]` / `[error]`；正文 `nCode` / `responseCode` / `response_nCode` **非 `0`** 即失败（`0`+`O.K.`=成功），伴 `strCodeDesc` / `responseCodeDesc` 给原因（如 `nCode:66302, strCodeDesc:UserRecordsRequest Fail for login:2512717`）；另：`result:`（非 `ok`）、`mtCode:`（非 `-1` = MT 侧有返回码 → **按 MT4/MT5 载对应 docs skill 查含义**，见 SKILL.md「MT 错误码」）、`[Abnormal]`（对应 `[Normal]`）、`elapsed_ms` 超 `threshold_ms`（慢/超时）；C++ 崩溃通用：`core dumped` / `SIGSEGV` / `abort` / `terminate`。
- **定位/业务类**：`server_id` / `serviceId`（如 `257m-skdf7roqg`）、`cmd:`（`get_history_deal` 等）、`login:`（账户号）、`connection uid` / `connection_uid`、`rid:`（**单机内**请求序号，≠ request_id）。

### 日志格式（两种并存）
**A · 结构化主格式**：`[时间] [级别] [logger或server_id] [线程] [file.cpp:line] [Class::Method] [标签...] 正文(key:value)`
```
[2026-06-11 14:25:07.208] [info] [sync_logger] [7448] [Server.cpp:1183] [CServer::RequestTaskHandle::RequestE2ELogGuard::~RequestE2ELogGuard] [REQUEST_E2E_TOTAL] [Normal] request_id:4e618c02505546d496c44a15e2de0997, server_id:257m-skdf7roqg, cmd:get_history_deal, connection_uid:71, elapsed_ms:171, threshold_ms:10000, response_nCode:0, mtCode:-1
[2026-06-11 14:25:07.208] [info] [257m-skdf7roqg] [7448] [ocs_timing.h:110] [OcsRequestGuard::~OcsRequestGuard] [rid:11511769] [End GetHistoryDeal] requestId:4e618c02505546d496c44a15e2de0997 elapsed:171ms
```
**B · 传输层格式**：`YYYY-MM-DD HH:MM:SS:mmm level 正文`（注意秒与毫秒间是 `:`）
```
2026-06-11 14:25:07:036 info [172.31.254.14:56788]receive data:W{"cmd":"get_history_deal",...,"request_id":"4e618c02505546d496c44a15e2de0997",...}QUIT
2026-06-11 14:25:07:036 info request [4e618c02505546d496c44a15e2de0997] send to [trading_system:257m-skdf7roqg:G] success, msg len:301
```

### 失败样例（含 MT4 后端 + ⚠️ VL 拼接坑）
失败请求（`cmd:select_account`，MT4 后端，`login:2512717` 用户记录请求失败，`nCode:66302`）：
```
[2026-06-11 14:51:13.687] [warning] [sync_logger] [28916] [Server.cpp:1055] [CServer::SendResponse] SendResponse End write, ... request_id:69f39c41..., cmd:select_account, response=>warn[nCode:66302, strCodeDesc:UserRecordsRequest Fail for login:2512717], mtCode:-1
[2026-06-11 14:51:13.687] [info] ... [REQUEST_E2E_TOTAL] [Normal] request_id:69f39c41..., cmd:select_account, ..., response_nCode:66302, mtCode:-1
[2026-06-11 14:51:13.675] [info] [7300-9ba858b5c] [21016] [ocs_timing.h:41] [mtapi_time_call] [rid:3628707] [End call UserRecordsRequest] [file:src\ocs\MT4\MT4TradeRequestHandle.cpp,line:1604] elapsed:172ms
```
- **怎么判**：`nCode/responseCode/response_nCode` 非 0（这里 `66302`）+ `strCodeDesc/responseCodeDesc` 给原因；`mtapi_time_call` 的 `[End call <MT接口>]`(这里 `UserRecordsRequest`) + `[file:src\ocs\MT4\...cpp,line:N]` 指出**失败发生在哪个 MT API 调用 + 精确源码位置**。注意：失败行 level 是 `[warning]`，但 `[Normal]`/`[REQUEST_E2E_TOTAL]` 仍可能出现（那是流程标记，不代表成功）——**以 nCode 为准**。
- **⚠️ VL 偶发日志拼接/截断**：单条 `_msg` 可能没写完就被**另一行日志拼接**进来（实例：`...mtCode:[2026-06-11 14:51:13.675] [info] ... [mtapi_time_call] ...` —— `mtCode` 的值被截、后面接了另一条完整行）。**worker 要稳健**：一行里出现**两个 `[时间戳]`** 就是拼接，拆开看；别因某字段被截/串就误判；以**多行交叉印证**为准（`REQUEST_E2E_TOTAL` 的 `response_nCode` 与 `SendResponse` 的 `strCodeDesc` 对齐）。

### 根因定位线索
- **请求调用链（OCS4 端到端）**：`上游 Java → gateway → ocs → mt(MT4/MT5) → 响应 ocs → 响应 gateway → 返回上游 Java`。判失败发生在哪一跳：ocs 日志里 `receive data`(入口报文)→`MT4Processor`/`MT5Processor`(调 MT)→`SendResponse`(回 gateway)；若 ocs 全程正常但上游仍报错，往 gateway / java 侧追；MT 侧异常看 `mtapi_time_call`(哪个 MT 接口失败) + `mtCode` + nCode。同一 `request_id` 贯穿整条链。
- **MT 后端分流**：`cmd` 决定走 MT4（`MT4Processor.cpp` / `CMT4Processor` / `src\ocs\MT4\MT4TradeRequestHandle.cpp`）还是 MT5（`MT5Processor.cpp` / `CMT5Processor` / `src\ocs\MT5\MT5TradeRequestHandle.cpp`）；具体哪个 MT 接口调用失败/耗时看 `mtapi_time_call` 行的 `[End call <接口>]` + `[file:...line:N]`。
- **MT Manager API 断连（OnDisconnect）· 常见告警**：日志形如 `[error] [<MT serverid>] [线程] [MT5Processor.cpp:NN] [CMT5Processor::OnDisconnect] ... MT5 Manager Api Disconnect, ServerID:<id>, processor_uid:N`（MT4 同理 `MT4Processor`/`CMT4Processor`）。含义 = **OCS 到该 MT（MT5/MT4）server 的 Manager 连接断了**，OCS 约 30s 后自动重启重连。**排查建议（重要）：这是 OCS↔MT server 之间的连接问题 → 应查对应 MT server 侧那段时间是否有重启 / 网络抖动 / server 异常**；`ServerID`（如 `cv1s-a2wsf1zla`）= 出问题的 MT server 实例。**绝不能只看 OCS 侧已自动重连就判"无需处理"**——根因在 MT/网络侧，要让用户去查 MT 日志。**先对照顶部「MT 维护/重启窗口」判断是否例行**：断连时间（北京）落在工作日 05:00~05:30（冬令时 +1h）或周末 13:00~14:00 多为**例行维护重启**（如实告知、非事故）；不在窗口则按非计划重启/网络排查。按告警排查时间窗见 SKILL.md「按告警排查」（告警晚于事件、窗口往前放宽）。
- **时间线（一次请求的生命周期标记，按序）**：`TASK_ENQUEUE → TASK_DEQUEUE → TASK_EXEC_START → TASK_COMPLETE → RESPONSE_WRITE → REQUEST_E2E_TOTAL`；每个带 `elapsed_ms` / `threshold_ms` → **慢在哪阶段一目了然**（哪段 elapsed_ms 接近/超 threshold_ms）。另有 `RedisCheckRequestID`（Redis 去重）、`receive data`（入口报文，含 JSON `request_data`：`login`/`from`/`to` 等业务参数）。
- **成功/失败**：看末尾 `REQUEST_E2E_TOTAL` 的 `response_nCode`（0=成功）与 `RESPONSE_WRITE` 的 `result`。失败则回溯到第一条 level=error/warn 或 nCode 非 0 的行。
- **C++ 源定位（接 code-analysis）**：每行 `[file.cpp:line]` + `[Class::Method]` 直接对到 ocs 源码（`src\ocs\...`，部分行还显式带 `[file:src\ocs\MT5\...cpp,line:NNN]`）。要到源码层继续追 → 提示在本话题换 code-analysis（service=ocs-v4、给 file.cpp:line + request_id）。
- **id 辨析**：`request_id`=端到端业务请求（32hex，跨组件追这条）；`rid`=单机内 OcsRequestGuard 序号（看某段耗时用）；`server_id`/`serviceId`=处理该请求的服务实例。
- **跨机**：PRD 多主体多机，同一 request_id 只会落在处理它的那台（先按 `env` 查 request_id，再看命中 host 反推主体）。

---

## ocs5（ocs-v5.* 版本）

- **别名 / 口语叫法**：`OCS5` / `ocs-v5` / `ocs5`
- **语言**：C++（gRPC 服务）
- **作用简述**：gRPC 查询服务 `saastoolscoreapi::SaasToolsCoreApiImpl`，对外提供 `GroupQuery` 等接口，bridge 到 MT4/MT5 查配置（如 group 设置、账户等）。每请求有 `request_uid`。
- **⚠️ 与 OCS4 关键差异（别套 OCS4 字段）**：
  - 主键是 **`request_uid`**（格式 `<8hex>-<数字>-<类型>`，如 `74ad6ed1-16095-group`）—— **不是** OCS4 的 32 位 hex `request_id`。
  - logger 是 **`async_logger`**（OCS4 是 `sync_logger`）。
  - 走 **gRPC**：请求/响应以 protobuf 文本记在 `[grpc.h:NNNN] [saastoolscoreapi::...::<Method>]` 行的 `request:` / `response:`；成功看 `task_status { result_desc: "success" }`。
  - 计时用 `[stopwatch::~stopwatch]`（`utils.cpp`），关联 `request_uid`、末尾 `<function>:line`——**有两种文本格式，见下方根因线索**。

### 各环境 × 机器（定位字段）

| env | project | host | 路径 / 备注 |
|-----|---------|------|------------|
| PRD（accountID=3） | `ocs5` | `WIN-L1HCGH1U47A`、`WIN-KVT0QOLECN8`（多副本） | `project:ocs5 env:PRD`（不指定 host 即跨副本）；日志 `C:/OCS5\data\prd\ocs5-<hash>-<pod>\RunLog\20-rotation.log`（pod 形如 `ocs5-585cb4c55c-sj9j6` / `-w78pm`，同 deployment 的 k8s 副本） |
| UAT（accountID=2） | `ocs5` | `dev-r1127-win-k8s-d4` | `project:ocs5 env:UAT host:dev-r1127-win-k8s-d4`；日志 `D:/OCS5\data\uat\ocs5-<hash>-<pod>\RunLog\20-rotation.log`（pod 形如 `ocs5-6c845d6f99-z2xkh`） |
| STG（⚠️租户=1，**查询通路待定**） | `ocs5` | `dev-r1127-win-k8s-d4`（**与 UAT 同机**） | 定位字段 `project:ocs5 env:STG host:dev-r1127-win-k8s-d4`（已确认）；**但 cpp STG 租户=1 而 probe 固定 stg=0、暂无覆盖入口 → 当前无法直接查**；日志 `D:/OCS5\data\stg\ocs5-<hash>-<pod>\RunLog\20-rotation.log`（pod 形如 `ocs5-7b89dbd64b-lhpxm`） |

> PRD 已知 2 台副本（`WIN-L1HCGH1U47A` / `WIN-KVT0QOLECN8`，同 deployment，可能更多）。**⚠️ UAT 与 STG 共用同一主机 `dev-r1127-win-k8s-d4`**——靠 `env` + 路径 `\uat\`/`\stg\` 区分（host 不足以分辨 UAT/STG）。**UAT 租户=2 正常查；STG 的 cpp 租户=1，probe 固定 stg=0 无覆盖入口 → 当前无法直接查、待定。**多副本 → 不指定 host、按 `project:ocs5 env:<环境>` + `request_uid` 跨副本查（一个请求只落在处理它的那台）。

### 主搜索键 = request_uid
`probe.py --term "<request_uid>"`（如 `74ad6ed1-16095-group`）全文搜，捞齐该请求的 request / response / stopwatch 各行。**用户甩来 `xxxx-数字[-类型]` 形态的串默认是 OCS5 的 request_uid。**

- **结构 = 基号 `<8hex>-<数字>` + 可选 `-<类型>` 后缀**：一个逻辑请求会派生子查询，子查询带类型后缀（如 `UserQuery` 用基号 `c6d25d77-15749`、`GroupQuery` 用 `c6d25d77-15749-group`）。**搜基号（`c6d25d77-15749`）可捞齐整组子查询**；只想要某子查询再带后缀。

### 常用关键词（python 筛用）
- **报错/异常类**：level `error`/`warn`、`task_status` 的 `result_desc` 非 `success`、`error`/`fail`/`exception`；C++ 崩溃通用：`core dumped`/`SIGSEGV`/`abort`/`terminate`。
- **定位/业务类**：`request_uid`、`server_id`（如 `6868-fec5e66d5`）、`app_id`、接口方法名（`GroupQuery` / `UserQuery` 等）、`group:`、`login:`、`mt4`/`mt5`。

### 日志格式样例
gRPC 请求/响应（同 `request_uid` 配对）+ stopwatch 计时：
```
[2026-06-11 23:42:28.692] [info] [async_logger] [63276] [grpc.h:3542] [saastoolscoreapi::SaasToolsCoreApiImpl::GroupQuery] request: request_uid: "74ad6ed1-16095-group" detail { mt4 { group: "demoEN-ECN" } } connection_info { server_info { app_id: "app972e7ff6917d" server_id: "6868-fec5e66d5" } }
[2026-06-11 23:42:28.696] [info] [async_logger] [63276] [grpc.h:3730] [saastoolscoreapi::SaasToolsCoreApiImpl::GroupQuery] response: request_uid: "74ad6ed1-16095-group" task_status { result_desc: "success" } detail { mt4 { detail { group: "demoEN-ECN" enable: 1 ... } } } json_result: "[{...}]"
[2026-06-11 23:42:28.696] [info] [async_logger] [63276] [utils.cpp:358] [stopwatch::~stopwatch] info level request_uid:74ad6ed1-16095-group | 4.53ms | saastoolscoreapi::SaasToolsCoreApiImpl::GroupQuery:3466
```

### 根因定位线索
- **gRPC 一问一答**：同 `request_uid` 的 `request:`（入参）+ `response:`（出参，含 `task_status.result_desc` 成功/失败 + `json_result`）。失败 = `result_desc` 非 `success` 或有 error/warn。
- **耗时**：`stopwatch` 行 `| <耗时> |` + 末尾 `<function>:line` → 各步耗时与位置（µs/ms 单位都有）。
- **C++ 源定位**：`[file.cpp:line]` + `[namespace::Class::Method]`（如 `saastoolscoreapi::SaasToolsCoreApiImpl::GroupQuery`）。`grpc.h:NNNN` 多是 gRPC 生成代码，真实逻辑看 `saastoolscoreapi` 实现 + `utils.cpp`；到源码层换 code-analysis（service=ocs-v5）。
- **bridge MT**：`detail { mt4 { ... } }` / `mt5` 表示查的是哪个 MT 平台的配置（group/账户等）。**若出现 MT 错误码 → 按 mt4/mt5 载对应 docs skill 查含义**（见 SKILL.md「MT 错误码」）。
- **MT 连接 / 连接池（慢的常见根因）**：`conn_pool.cpp [get_manager_wrapper_from_lru] [lru:mt5|mt4]` 的 `miss`/`hit` + `common.cpp [mt5::manager_wrapper::manager_connect_server | admin_connect_server]`（`server:<ip:port> user:<mgr登录> code:0`=连成功）。**LRU `miss` → 新建到 MT 的连接是常见耗时点**（UAT 实测 `UserQuery elapsed:1494.491ms` 即 miss 后建连所致）；MT 服务器地址/管理登录见这些行（如 `10.1.64.18:2003 login:1098`）。
- **其它已知行类型**：`idempotence_guard`（幂等校验；`idempotence_id`/`app_id`/`server_id` 任一空则跳过）、`[apm] handler_start ... request_uid=... trace_id=`（APM；`trace_id` 有时为空、有时是 32hex（如 STG 样例 `ed7e0dfb...`）——**非空时也可作 `--term` 关联键**）、`validate_mtserver_availability`（MT server 可用性校验）。
- **stopwatch 有两种格式**（都按 `request_uid` 关联，看末尾 `<func>:line` 定位）：`... <步骤> | <耗时> | <func>:line`（`utils.cpp:358`）或 `... <步骤> elapsed:<耗时> ... at <func>:line`（`utils.cpp:355`）。
- 时区遵顶部三时区约定（OCS5 各机偏移不一：PRD≈北京；**UAT/STG 机器 = UTC-8 + 夏令时（实际 UTC-7），对北京晚 15h**，且夏令时随季节切换——按需换算）。

---

<!-- 新增服务：复制一段 ## <服务名> 模板填入，并同步在 references/README.md 路由表加一行（名称/口语/键形态触发词）；SKILL.md 不用改。 -->
