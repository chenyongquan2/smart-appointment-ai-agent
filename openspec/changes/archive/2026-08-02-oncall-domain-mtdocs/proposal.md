## Why

OnCall 路线第 3 期切片 3,收尾。切片 1 能查日志、切片 2 能读源码,还差最后一类问题:**MT4/MT5 平台本身的 API 语义**——某个返回码是什么意思、某个接口的参数怎么解释。

值守域已有的 `load_reference` 覆盖了公司**自研**的错误码(OCS4 的 66xxx 段、OCS5 的 `result_code`),但 MT 平台原生的 `RET_*` / `MT_RET_*` 与 API 行为在**平台文档**里,那是两套东西。切片 1 移植的分诊表最后一行写的就是这个分流:reference 查不到该码时,要去查 MT 平台文档。

## 先回答一个自然的疑问:为什么不直接让 AI 读 `/mt4-api-docs` skill?

因为**能读它的 AI 不是跑值守 bot 的那个**。三个运行时,三套机制:

| 运行时 | skill 机制 | 装在哪 |
|---|---|---|
| Claude Code(开发时) | 有 Skill 工具 | `~/.claude/skills/mt4-api-docs/` |
| 参考系统的 worker | opencode 的 `skill({name})` | `.opencode/skills/mt4-docs/` |
| **值守 bot(本项目)** | **没有** | — |

值守 bot 是 harness 里的 agent:FastAPI 进程 + tool registry。它没有 skill 机制(`remove-skills-skeleton` 按 YAGNI 移除过),也没有通用文件系统工具(切片 2 那两个 jail 在 worktree 内)。更实际的是:`~/.claude/skills/` 是**开发者本机的 Claude Code 安装路径**,部署到服务器上不存在。

**也不打算为此在 harness 里补 skill 机制**:skill 的不可替代之处是"程序性指令多到不能全塞提示、需按情形动态加载";这里要的是"给关键词、返回相关文档段",那是检索,FTS 正是干这个的。为它引入一整套 skill 机制是拿大炮打蚊子。

**但数据必须复用、不重建**——两个 FTS 库是现成的:

```
mt4docs.db   468K   toc_fts(3) / category_fts(35) / function_fts(197)
mt5api.db     12M   api_class_fts(575) / api_method_fts(4834)
```

本切片的活是**接上它们**,不是造库。

## What Changes

- **新增 `services/mt_docs.py`**:只读打开两个 SQLite FTS 库,按平台路由到对应的 FTS 表,BM25 排序,返回 `标题 + 摘录 + 文档 URL`。
- **新增 `mt_docs_search` 工具**:`platform`(mt4/mt5)+ `query`,`dangerous=False`。
- **数据走配置路径 `ONCALL_MT_DOCS_DIR`,不进版本库**(见下)。
- **prompt 补 MT 文档的分流规则**:什么码段该查 reference、什么该查平台文档;怎么从日志判断走 MT4 还是 MT5。

## 三条判断

**1. 12M 的 db 不进 git,走配置路径**

两个库是**别处维护的知识快照**,本仓只是使用方。塞进版本库后每次更新都是一个 12M 的二进制 diff,而且 git 对二进制无法增量。故走 `ONCALL_MT_DOCS_DIR` 配置,未配置时**明确失败**——与 `KnowledgeSearchPort`("知识库未接入")、`VM_LOGS_*` 同一套路子:不静默返回空,那会被模型读成"查过了、文档里没有"进而编造 API 语义。

**2. FTS5 的查询语法必须防御**

用户的问题里带 `()`、`-`、`"` 是常态(如 `OrderSend()`、`MT_RET_REQUEST_*`),这些字符在 FTS5 MATCH 里有语法含义,直接拼进去会抛 `fts5: syntax error`。必须把用户输入**当字面量处理**(分词后逐词加引号),而不是原样塞进 MATCH。这是本切片最容易被漏掉、且一定会在真实使用中触发的一处。

**3. sqlite 是同步阻塞的,同样下沉线程池**

虽然是本地文件、通常毫秒级,但 12M 的库上一次没走索引的查询可以到百毫秒量级,而且**规则要一致**:本项目已经三次栽在"同步调用混进 async handler"上(知识库检索、技师匹配、险些的 vlog)。连接用 `mode=ro` 只读打开——值守域连读文档都不该有写的可能。

## Capabilities

### Modified Capabilities
- `oncall-domain`: 新增「MT 平台文档检索」需求——按平台路由、查询字面量化(防 FTS5 语法注入与语法错误)、未配置时明确失败而非返回空、只读打开。

## Impact

**新增**:`services/mt_docs.py`、`config/mt_docs_config.py`、`domains/oncall/tools/mtdocs.py`。

**改动**:`domains/oncall/tools/__init__.py`(第六个工具)、`domains/oncall/prompt.py`(MT 文档分流规则)、`.env.example`。

**不改**:`harness/`、`executor/`、`channels/`、预约域、`evals/`。

**测试**:**本切片是三片里唯一能端到端验证的**——FTS 库是本地文件,不需要内网或凭据。测试用**临时构造的小型 FTS 库**(造几行 mt4/mt5 形状的数据),验路由、排序、摘录、特殊字符查询、未配置时的明确失败、只读连接拒绝写入。

⚠ 与前两片不同,本切片**不留人工冒烟挂起项**:若配了 `ONCALL_MT_DOCS_DIR` 指向真实库,本机即可完整验证。
