## Context

值守域已能查日志(切片 1)、读源码(切片 2)。剩下的一类问题是 **MT 平台本身的 API 语义**：`mtCode` 是什么含义、某个接口的参数怎么解释。

已有的 `load_reference` 覆盖的是公司**自研**码（OCS4 的 66xxx、OCS5 的 `result_code`），MT 平台原生的 `RET_*` / `MT_RET_*` 在**平台文档**里——切片 1 移植的分诊表最后一行写的正是这个分流。

现成的两个 FTS 库形状不同，这是本切片主要的实现约束：

| 库 | FTS 表 | 行数 |
|---|---|---|
| `mt4docs.db`(468K) | `toc_fts` / `category_fts` / `function_fts` | 3 / 35 / 197 |
| `mt5api.db`(12M) | `api_class_fts` / `api_method_fts` | 575 / 4834 |

列也不同：mt4 的 `function_fts` 有 `signature/parameters/remarks/return_value`；mt5 的 `api_method_fts` 有 `class_name/method_name/signature_cpp/signature_net/...`。

## Goals / Non-Goals

**Goals:**
- 模型能按关键词查到 MT4/MT5 的 API 与返回码含义，拿到**标题 + 摘录 + 文档 URL**。
- 数据复用现成的 FTS 库，不重建语料。
- 查询对用户输入里的特殊字符鲁棒（`OrderSend()`、`MT_RET_*` 这类是常态）。

**Non-Goals:**
- 不为此在 harness 里补 skill 机制（proposal 已论证）。
- 不重建/不维护文档语料——本仓只是使用方，库由别处更新。
- 不做跨平台的统一抽象层：mt4 与 mt5 的 schema 差异是**真实的**，硬抽象只会让两边都别扭。按平台分派、各自查各自的表。
- 不做向量检索。FTS + BM25 对"查某个 API 名/错误码"这种**关键词精确**场景足够；上向量反而在这类查询上更差。

## Decisions

### D1 数据走配置路径，不进版本库

`ONCALL_MT_DOCS_DIR` 指向含 `mt4docs.db` / `mt5api.db` 的目录。缺省不设，未配置时**明确失败**。

**为什么不 vendor**：12M 的 `mt5api.db` 是别处维护的知识快照，塞进 git 后每次更新都是一个 12M 的二进制 diff，且 git 对二进制无法增量——仓库会以每次更新 12M 的速度膨胀。本仓只是使用方。

**为什么未配置时要明确失败**：与 `KnowledgeSearchPort`（"知识库未接入"）、`VM_LOGS_*` 完全同一套路子。返回空结果会被模型读成"查过了、文档里没有这个码"，进而**凭训练知识编造 API 语义**——在值守场景里，编造一个返回码的含义比说"查不到"危险得多。

### D2 ★ 查询字面量化，不把用户输入原样塞进 MATCH

这是本切片最容易漏、且**一定会在真实使用中触发**的一处。

FTS5 的 MATCH 有自己的语法：`"` 引号短语、`*` 前缀、`-` 排除、`()` 分组、`AND/OR/NOT` 操作符。而用户的问题里带这些字符是常态——`OrderSend()`、`MT_RET_REQUEST_*`、`ERR_NO_ERROR`。原样拼进去的结果是 `sqlite3.OperationalError: fts5: syntax error near "("`。

做法：把输入按非字母数字切成词，每个词用双引号包起来（内部的 `"` 转义成 `""`），再用空格连接（FTS5 里空格即 AND）。于是 `OrderSend()` → `"OrderSend"`，`MT_RET_REQUEST_*` → `"MT" "RET" "REQUEST"`。

**代价与取舍**：这样做丢掉了用户显式使用 FTS 语法的能力（比如故意用 `-` 排除）。接受——这个工具的调用方是 LLM 不是 SQL 专家，让它不必学 FTS5 语法、且不会被语法错误挡住，远比保留高级语法有价值。切片 1 的 `vlog_query` 是相反的选择（保留了原始 LogsQL 入口），因为那边的查询语言是排障的核心技能、值得让模型学。

### D3 按平台分派，不做统一抽象

mt4 查三张表、mt5 查两张，列名与语义都不同。考虑过抽一层"统一文档模型"，否决了：抽象要么丢字段（mt5 的 `signature_cpp`/`signature_net` 双签名在 mt4 里没有对应）、要么变成一堆 Optional 的大杂烩。

分派更诚实：每个平台一个查询函数，各自知道自己该查什么表、怎么组结果。共用的只有"连接管理 + 查询字面量化 + 结果封装"。

**平台怎么定**：作为**必填参数**由模型给，不猜。切片 1 的分诊表已经给了模型判据（日志里见 `CMT4Processor` / `detail{mt4}` 走 MT4，见 `CMT5Processor` / `detail{mt5}` 走 MT5），prompt 里再强调一次。猜错平台会查出完全无关的结果，而它自己不知道。

### D4 只读连接 + 下沉线程池

连接用 `sqlite3.connect("file:...?mode=ro", uri=True)`：值守域连读文档都不该有写的可能，`mode=ro` 让"写"在驱动层就不可能，而不是靠"我们没写 INSERT"的自觉。

`sqlite3` 是同步阻塞的。虽然本地文件通常毫秒级，仍下沉 `asyncio.to_thread`——12M 的库上一次没走索引的查询能到百毫秒量级，更重要的是**规则要一致**：本项目已经三次栽在"同步调用混进 async handler"（知识库检索、技师匹配、险些的 vlog）。每次都是"这次很快、没关系"的想法开的头。

### D5 结果带 URL，且要求模型转达

两个库的每张表都有 `url` 列（指向 MT 官方文档页）。结果里带上并在 description 里要求转给用户——**回答一个 API 的语义时给出可核对的出处**，这与值守域"不猜、可核对"的整体风格一致，也让用户能自己深入。

## Risks / Trade-offs

- **[丢掉 FTS 高级语法]** → D2 的自觉代价。缓解：调用方是 LLM，不需要那些语法；避免语法错误的价值更大。
- **[库未配置时工具不可用]** → 缓解：明确失败 + 可操作的提示（"未配置 `ONCALL_MT_DOCS_DIR`"），而不是静默空结果。
- **[平台猜错查出无关结果]** → 缓解：平台必填、prompt 给判据；结果带 URL 便于用户一眼看出查岔了。
- **[库的 schema 将来变化]** → 本仓只是使用方，schema 变了这里要跟着改。缓解：测试用**自造的小库**验 schema 假设，schema 一变测试就红，不会等到线上。

## Migration Plan

1. `config/mt_docs_config.py` + `services/mt_docs.py` + 用自造小库驱动的测试。
2. `mt_docs_search` 工具接上。
3. prompt 补分流规则。
4. 若本机配了真实库路径，跑一次真实查询确认（本切片**不需要**内网或凭据）。

**回滚**：单分支 revert。

## Open Questions

- 是否要把 mt4/mt5 的 434 个 markdown 也接进来（FTS 库是从它们生成的）——本切片不做：FTS 已覆盖检索需求，markdown 是生成源、不是查询面。
