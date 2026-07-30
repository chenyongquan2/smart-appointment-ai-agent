# 设计：修复向量化调用无超时且阻塞事件循环

## Context

现状（均已读代码/实测确认）：

- `config/model_provider.py:create_embedding_model()` 创建 `OpenAIEmbeddings` 时**不传任何超时**。实测该实例 `timeout` 未设置、`request_timeout` 为 `None` → 落到 openai 客户端默认 600 秒。
- `services/text_embedding.py:embed_input(..., timeout: int = 600)` 的 `timeout` **从未被使用**，函数体只有两行：建模型 + `embeddings.embed_query(text)`。签名里那个 600 是对客户端默认值的无效复述。
- `embed_query` 是**同步**调用。`services/knowledge_service.py` 有 **6 处**调用它，全部位于 `async def` 内（`search` / `initialize` / `_create_default_knowledge` / `_build_vector_index` / `add_document` / `update_document`）。
- 每次 `embed_input` 都重新 `create_embedding_model()`，即每次调用新建一个客户端。

后果链：同步阻塞调用跑在事件循环上 → 请求挂住即占住整个循环 → `asyncio.wait_for` 的定时器回调都无法执行 → **任何外层超时都失效**。已归档 change `feishu-channel-integration` 把飞书长连接放进同一进程（其 design D7），于是这个缺陷的后果从「跑批卡住」升级为「收包与心跳一起停摆、机器人静默失联且不报错」。

实测证据（两次可复现）：进程 CPU 8 秒零增长、2 个 `ESTABLISHED` :443 + 9 个 `CLOSE_WAIT`、日志静默十余分钟；同期独立量 LLM 延迟正常 1.4–2.5s。

约束：`services/` 与 `config/model_provider.py` 在 `openspec/project.md` 的「不要动（保留资产）」清单上——该清单禁的是**重写业务逻辑**，本变更只加超时与异步路径。

## Goals / Non-Goals

**Goals:**
- 任何一次向量化调用都有明确、可配置的时间上限，绝不无限期挂起
- 向量化不再阻塞事件循环，使外层超时（含 `Tool.timeout`）真正可生效
- 挂起场景可被离线确定性测试覆盖（注入永久挂起的 fake，不触网）
- evals 门禁恢复可跑

**Non-Goals:**
- 不改 RAG 检索逻辑、不动 SQLite+FAISS 基础、不重写 `KnowledgeService` 任何业务规则
- 不修「`text-embedding-3-small` 在当前网关不可用」（独立配置问题，另有任务跟踪）
- 不给 `KnowledgeService` 加缓存或客户端复用（见 D4——诱人但属另一件事）
- 不改 LLM 侧的超时/重试（`guarded_invoke` 已有，不重复造）

## Decisions

### D1 超时施加在客户端构造处，而非调用处包一层 `wait_for`

`create_embedding_model()` 接受并默认施加超时，取值来自 `EMBEDDING_TIMEOUT_SECONDS`（缺省 20 秒）。

- **为什么不在调用处 `asyncio.wait_for` 就完事**：那只在调用可被取消时有效。本缺陷的根因恰恰是调用**不可被取消**（同步阻塞），所以外层包装是治标——而且会给人「已经有超时了」的错觉，正是当前 `timeout=600` 那个假参数造成的问题。让 HTTP 客户端自己带超时，是唯一在任何调用形态下都成立的防线。
- **两层都要**：客户端超时（本条）解决「请求永不返回」；D2 的异步化解决「阻塞事件循环」。缺任一条，另一条都不完整——客户端超时若配在同步调用上，20 秒内事件循环仍然是冻的。
- **20 秒的依据**：向量化是单次、无生成的短请求，正常在秒级完成；600 秒等于没有上限。取 20 秒留足网络抖动余量，又远小于任务墙钟上限（600s）与 LLM 单次超时（30s）的量级秩序。
- 备选：写死常量——但不同网关的实际延迟差异大，配置化的成本几乎为零。

### D2 新增 `aembed_input()` 走 LangChain 原生 `aembed_query`，而非 `asyncio.to_thread`

已确认 `OpenAIEmbeddings` 提供 `aembed_query`。

- **为什么原生异步优于 `to_thread`**：`to_thread` 能让事件循环不被阻塞，但线程里的同步调用**依然不可取消**——`wait_for` 超时后协程被取消，那个线程还在后台跑到自己结束，连接与线程都泄漏。原生异步走 httpx 的异步栈，取消是真取消。
- **保留同步 `embed_input`**：`find_best_match_indices` 等同步调用点不在事件循环关键路径上，改成异步会波及它们的所有调用方。两个函数并存、共用同一套超时配置，是最小侵入的做法。
- 备选：把 `embed_input` 直接改成 async——会破坏所有同步调用方，属于「重写」，违反保留资产约束。

### D3 只改 `async` 上下文里的调用点

`KnowledgeService` 的 6 处调用全部位于 `async def` 内，故全部改为 `await aembed_input(...)`。

- `search` 是**热路径**（每次 `search_knowledge` 工具调用都走它），必须改。
- `initialize` / `_build_vector_index` / `_create_default_knowledge` 是启动期批量向量化，不并发、但同样会在启动时冻住循环（且它们循环调用多次，累积阻塞更久）。既然都在 `async def` 里，一并改，不留半吊子。
- `add_document` / `update_document` 走管理端 API，同理。

### D4 不顺手做客户端复用与缓存

每次 `embed_input` 都新建客户端确实浪费（建连开销、无连接池复用），改成模块级单例是很自然的下一步。**但本变更不做**：它属于性能优化，与「不能挂死」是两件事，混进来会让这个修复的边界与验证都变模糊。已在实施清单里作为后续项记录，不在本变更范围。

### D5 测试用「永久挂起的 fake」而非依赖真实慢请求

注入一个 `aembed_query` 永不返回的 fake embedding，断言调用在超时内以错误收场。

- 这是唯一能**确定性**覆盖挂死场景的方式；靠真实慢请求既不可重复也要触网。
- 同时补一条断言：事件循环在等待期间仍能推进（另起一个协程，验证它按时被调度）——这条才真正区分「有超时」和「不阻塞」，二者是不同的缺陷，需要分别守住。

## Risks / Trade-offs

- [20 秒对某些网关偏紧，正常请求被误杀] → 可经 `EMBEDDING_TIMEOUT_SECONDS` 上调；且超时被 `KnowledgeService` 现有的 try/except 收成「检索失败」并回灌给模型，不崩请求。相比「无限期挂死」，误杀是可恢复的。
- [超时后检索静默返回空，看起来像「不报错但永远没结果」] → `KnowledgeService.search` 现有实现会记 ERROR 日志（当前 503 就是这样暴露的），保持该行为；日志里查得到。
- [同步 `embed_input` 仍然存在，将来有人在 `async` 里误用它] → 在两个函数的 docstring 里互相指明「async 上下文用 `aembed_input`」，并在 `openspec/project.md` 的工具编写约定处已有同类告示（`Tool.timeout` 对同步阻塞无效那条）。这是约定而非强制，属残余风险。
- [`aembed_query` 在某些 provider 上未实现或行为不一致] → Azure 与 OpenAI 兼容两条路径都由 LangChain 的同一基类提供该方法；若某 provider 缺失，回退到 `to_thread` 包装（次优但不阻塞循环），实施时若遇到再定。
- [改了 6 处调用点，可能漏掉某处] → 实施后以 `grep -n "embed_input" services/` 逐一核对，确保 `async def` 内不再有同步调用。

## Migration Plan

无数据迁移。按顺序分两步，每步可独立验证：

1. 超时落地（`create_embedding_model` + `embed_input` 真正透传）+ `.env.example`。此时挂死风险已从「永久」降为「至多 20 秒」，但事件循环在这 20 秒内仍会被冻住。
2. 异步路径（`aembed_input` + 6 处调用点）。此时事件循环不再被阻塞。

回滚：两步都是加法（新增参数/新增函数/改调用点），回滚即还原调用点；`EMBEDDING_TIMEOUT_SECONDS` 留空时可退回原行为（不建议，仅作应急）。

## Open Questions

- `EMBEDDING_TIMEOUT_SECONDS` 的缺省值 20 秒是否合适，需在真实网关上观察一次正常请求的延迟分布后确认（当前该网关上模型不可用，无法立即观察；缺省值可先按 20 落地，后续按实测调）。
