> **本切片与前两片的关键差别**：它**不依赖内网或凭据**——FTS 库是本地文件，
> 配好 `ONCALL_MT_DOCS_DIR` 即可完整验证。故**不留人工冒烟挂起项**。

## 1. config + services/mt_docs.py

- [x] 1.1 `config/mt_docs_config.py`：`ONCALL_MT_DOCS_DIR` 解析 + 两个库文件名常量。未配置或文件缺失时抛**明确区分"配置缺失"与"查无此项"**的异常——两者混淆会让模型把配置问题当成"文档里没有"，进而编造 API 语义。
- [x] 1.2 只读连接：`sqlite3.connect("file:...?mode=ro", uri=True)`。**驱动层只读**，不靠"我们没写 INSERT"的自觉（design D4）。
- [x] 1.3 ★ **查询字面量化**：按非字母数字切词，每词加双引号（内部 `"` 转义为 `""`），空格连接。`OrderSend()` → `"OrderSend"`；`MT_RET_REQUEST_*` → `"MT" "RET" "REQUEST"`。**这是本切片最容易漏、且真实使用中必然触发的一处**——不做的话 `OrderSend()` 直接抛 `fts5: syntax error near "("`。
- [x] 1.4 按平台分派（design D3，不做统一抽象）：
      - mt4 → `function_fts`（signature/parameters/remarks/return_value）+ `category_fts` + `toc_fts`
      - mt5 → `api_method_fts`（class_name/method_name/signature_cpp/signature_net/...）+ `api_class_fts`
- [x] 1.5 BM25 排序 + `snippet()` 取摘录；结果统一封装为 `{title, snippet, url, table}`，带上来源表便于判断命中的是函数还是分类。
- [x] 1.6 下沉 `asyncio.to_thread`。本地文件通常毫秒级，但 12M 库上没走索引的查询能到百毫秒，**且规则要一致**——本项目已三次栽在"同步调用混进 async handler"，每次都是"这次很快、没关系"开的头。
- [x] 1.7 测试用**自造的小型 FTS 库**（按真实 schema 造几行 mt4/mt5 形状的数据）：路由正确、排序有序、摘录非空、**特殊字符查询不报语法错误**、未配置时明确失败、只读连接拒绝写入、schema 假设被验证（库将来变了测试就红）。

## 2. mt_docs_search 工具

- [x] 2.1 `platform` 必填（`mt4` / `mt5` 枚举）、`query` 必填、`limit` 有上限。`dangerous=False`。
- [x] 2.2 description 写清**分流**：公司自研码（OCS4 66xxx / OCS5 result_code）查 `load_reference`；MT 平台原生码（`RET_*` / `MT_RET_*` / `mtCode`）与 API 语义查本工具。**两套体系别混**。
- [x] 2.3 description 写清**怎么判平台**：日志里见 `CMT4Processor` / `src\ocs\MT4` / `detail{mt4}` 走 mt4；见 `CMT5Processor` / `detail{mt5}` 走 mt5。**猜错平台会查出完全无关的结果而你不会察觉**。
- [x] 2.4 description 要求**把文档链接转给用户**——回答 API 语义时给出可核对的出处，与值守域"不猜、可核对"的风格一致。
- [x] 2.5 进 `TOOLS`；域装载后共六个工具、全 `dangerous=False`。

## 3. prompt 补 MT 文档分流

- [x] 3.1 分诊表补一行：MT 平台原生码 / API 语义 → `mt_docs_search`（现有那行只指向 `mt-returncode` 资料，那是速查表、覆盖不全）。
- [x] 3.2 写明三层查法：先判码段 → 自研码查 reference → 平台码查 reference 的速查表 → **速查表未覆盖（如 SDK 新增码）才查 mt_docs_search**。reference 是本地文件、比检索快且省 token。

## 4. 验证与收尾

- [x] 4.1 `uv run pytest` 全绿，差额说清。
- [x] 4.2 冒烟：`AGENT_DOMAIN=oncall` 起服务，registry 六个工具齐、全只读。
- [x] 4.3 ✅ **真库端到端已验证**：从参考系统拷来 `mt4docs.db` / `mt5api.db`，配 `ONCALL_MT_DOCS_DIR` 后经 registry → 工具 → service → FTS 全链路跑通（`CManagerInterface::TradesRequest` 命中 3 条、摘录为「Gets all open orders of all clients.」）。**本切片不留人工冒烟挂起项。**
- [x] 4.4 更新 `docs/oncall-bot-roadmap.md`：第 3 期三片全完成；标注两个仍挂起的人工冒烟（切片 1 的 `VM_LOGS_*`、切片 2 的真实 git 仓库）。
- [x] 4.5 更新记忆 `eval-progress-state` 或新增一条：第 3 期完成、第 4 期（oncall 评估闭环）是下一步。


## 5. 真库验证抓到的两处（离线测试没覆盖到的）

- [x] 5.1 **摘录取成了 URL**：`snippet(table, -1, ...)` 的 -1 是「命中哪列取哪列」，而 url 列里常含关键词（查 `Connect` 会命中 `.../manager_api_connect/...`），于是摘录变成一串 URL、毫无信息量。改为**固定取描述列**（各表的列序号写进表配置）。补了回归测试。⚠ 自造的小库没暴露这个问题——因为造数据时 URL 恰好不含检索词。**这正是真库验证不可替代的地方。**
- [x] 5.2 **两个库装的都是 Manager API，不是 MQL4/MQL5 语言参考**：`mt4docs.db` 里是 `CManagerInterface::*`，拿 `OrderSend`（MQL4 语言函数）去查是 0 命中——**这是正确行为**，但模型不知道这个边界就会把「不在本库范围内」误报成「该 API 不存在」，那是个自信的错误结论。已写进工具 description 与 prompt，并补测试守住。
