## Why

OnCall 路线第 3 期。第 1 期把管道通到了飞书群、第 2 期把「域」做成了可装载的包，但**装在管道里的仍是按摩预约**——bot 会跟你聊预约，不会查日志。本期开始填真正的值守能力。

参考系统 `C:\workspace\lark-oncall-bot` 已在 34 人群运行，趟平了坑；本期移植它最核心的一块：**VictoriaLogs 日志查询**。

## 本期范围：第 3 期的第 1 切片

第 3 期整体（`vlog` + `repo` + `docs_search` 三个服务、1050 行移植、三个工具、域包、97KB 知识库路由）**一次做完太大**，一个审阅闸门扛不住。按纵向切片走，每片自成可用闭环：

| 切片 | 内容 | 状态 |
|---|---|---|
| **1（本期）** | oncall 域骨架 + `services/vlog.py` + `vlog_query` 工具 + 知识库按需加载 | 本变更 |
| 2 | `services/repo.py`（`repokit.py` 669 行）+ `code_analysis` 工具 | 后续 |
| 3 | `services/docs_search.py`（MT4/MT5 FTS 库）+ `mt_docs_search` 工具 | 后续 |

选日志查询打头，因为它是值守的**主动作**——"查日志 → 看懂 → 定位"这条链能单独跑通就已经有用；代码分析与文档检索是它的辅助。

## What Changes

- **新增 `domains/oncall/`**：按第 2 期定下的五槽位填——`tools/`、`subagents/`、`prompt.py`（值守人设与红线）、`policy.py`（**全工具只读，硬 enforce**）、`evals/`（本期留空目录，第 4 期填）。注册进 `domains/_DOMAINS`，`AGENT_DOMAIN=oncall` 即可切换。
- **新增 `services/vlog.py`**：移植 `probe.py`（381 行）的能力——LogsQL 查询、env→accountId 多租户映射、两种模式（发现 / 精确窗）、vmui URL 解析与生成、代理绕行、错误分类。**改为 async + httpx**（原实现是 `urllib.request` 同步阻塞，见 design D1）。
- **新增 `vlog_query` 工具**：薄封装 `services/vlog.py`，`dangerous=False`（纯只读）。
- **新增 oncall 知识库与按需加载**：把参考系统的 4 份 reference（`ocs-service-profiles.md` / `mt-returncode.md` / `ocs4-returncode.md` / `ocs5-returncode.md`，共约 97KB）与那张**路由表**一起移植。路由表进 system prompt（它只有 20 行），reference 本体经一个 `load_reference` 工具**按需读取**——97KB 全塞上下文既贵又稀释注意力。
- **凭据接线**：`VM_LOGS_URL` / `VM_LOGS_USER` / `VM_LOGS_PASSWORD` 进 `.env.example` 与 `config/`，**只在 service 层读取，绝不进 LLM 上下文**。
- **不动的部分**：`harness/`、`executor/`、`channels/`、预约域一律不改。第 2 期立的领域包契约本期第一次被真正检验——**若需要改 `harness/` 才能装下 oncall 域，那说明第 2 期的抽象漏了，要回头修抽象而不是在这里打补丁**。

## Capabilities

### New Capabilities
- `oncall-domain`: 值守域的能力边界——只读红线、日志查询语义（发现/精确窗两模式、env→租户映射、vmui URL 往返）、知识库按需加载路由、以及"查询失败如实转达不武断归因"。

### Modified Capabilities
- `guardrails`: 「多候选向量化 SHALL 异步并发」那条已把"非 LLM 外部 I/O"锚到具体调用点；本期新增一个同类锚点——**日志查询 client SHALL 走异步且自带秒级超时**。这不是新约束，是把既有的「外部调用超时与非阻塞」再落到一个具体实现上（原实现是同步 `urllib`，直接移植会重演已修过两次的缺陷）。

## Impact

**新增**：`domains/oncall/`（五槽位 + 4 份 reference）、`services/vlog.py`、`config/` 的 vlog 凭据读取。

**改动**：`domains/__init__.py`（注册 oncall）、`.env.example`（VM_LOGS_* 三键）、`pyproject.toml`（`httpx` 从 dev 依赖提为运行时依赖——它已作为 starlette TestClient 的依赖存在）。

**不改**：`harness/`、`executor/`、`channels/`、`domains/appointment/`、`evals/`（数据与机制都不动）。

**测试**：全部离线——注入 fake HTTP 传输，不触真实 VictoriaLogs。含：两种模式的查询构造、env→accountId 映射、vmui URL 解析与生成往返、错误分类（timeout / connect_failed / http_error）、**心跳不停**（沿用 `fix-technician-embedding-blocking` 的范式，守住异步非阻塞）、只读策略拒绝写工具、知识库路由命中与未命中。

**评估**：`evals/` 一行不改。oncall 用例集属第 4 期，本期只留空目录。预约域评测冻结决策不受影响。

⚠ **验收口径**：本期无法端到端验证真实日志查询（需内网 + 凭据）。离线测试证明的是"请求构造正确、异步不阻塞、失败分类正确"；**"查得对不对"要用真实凭据手动冒烟**，结论要如实区分这两者。
