## Context

`fix-embedding-timeout-blocking`（archive `2026-07-30`）确立了两条互补的约束，并把它们写进 `guardrails` spec：客户端自带秒级超时 + async 上下文不得同步阻塞。当时的修复只覆盖了知识库检索那条链（`KnowledgeService.search` → `aembed_input`），技师专长匹配这条**没被发现**。`remove-local-rag`（2026-08-02）删掉知识库后，技师这条成了项目里唯一的违规点。

为什么当时会漏：`find_best_match_indices` 位于 `services/text_embedding.py`，看起来是"embedding 模块自己的辅助函数"；而它的调用方在 `agents/appointment/technician_finder.py`——一个名字里完全没有 embedding 字样、且属于"遗留 agents 层"的文件。`embed_input` 的 docstring 甚至把 `find_best_match_indices` 明确列为"确实不在事件循环关键路径上的同步调用点"——**那句话本身就是错的**，它恰恰在关键路径上。这是本次值得记下的教训：判断"是否在事件循环关键路径"不能只看直接调用者，要沿调用链一路查到入口。

## Goals / Non-Goals

**Goals:**
- 技师专长匹配在 async 上下文中不再冻住事件循环，且调用可被取消。
- 顺带把 N+1 次串行请求改为并发（同一次改造的自然产物，不额外增加复杂度）。
- 给这条路径留下可执行的回归守卫，使同类缺陷下次能被测试而非事故发现。

**Non-Goals:**
- **不改匹配语义**：同样用 embedding 相似度排序，结果必须与改前一致。
- **不做向量缓存/持久化**：技师专长是静态数据，每次调用都重算 N 个向量确实浪费（`services/text_embedding.py` 里甚至还躺着没人用的 `save_technician_embeddings` / `load_technician_embeddings`）。但缓存涉及失效策略与换模型时的维度陷阱，是独立取舍，不塞进这次。
- **不把技师匹配去 embedding 化**：那会改变匹配结果、影响 `appointment` 类的任务成功率，属能力取舍而非缺陷修复。
- 不动其余同步的本地 SQLite 调用——它们是毫秒级本地 I/O，与 20 秒量级的远程 HTTP 不是一个问题。

## Decisions

### D1 异步化整条链，而不是 `asyncio.to_thread` 下沉

`asyncio.to_thread(find_best_match_indices, ...)` 是最小改动，但**只解一半问题**：事件循环不再冻住，可线程里的同步调用**依然不可取消**——超时后协程被取消，那个线程仍会在后台跑到自己结束，连接与线程都泄漏。这个取舍在 `fix-embedding-timeout-blocking` 的 design D2 里已经辨析过并明确否决，本次沿用同一结论，不再重复论证。

故走原生异步：`aembed_input` → LangChain 的 `aembed_query` → httpx 异步栈，取消是真取消。

### D2 用 `asyncio.gather` 并发取候选向量

现状是 `[embed_input(c) for c in candidates]` 串行，N 个技师就是 N 次串行 RTT。改成 `await asyncio.gather(*(aembed_input(c) for c in candidates))` 后一轮打完。

- **失败语义不变**：`gather` 默认 `return_exceptions=False`，任一候选失败即整体抛出——与现在串行循环中途抛出的行为一致，调用方（agent loop 的 `_dispatch`）照旧吞成"工具执行失败"回灌。刻意**不用** `return_exceptions=True` 做部分降级：那会让"部分候选没有向量"变成一个需要在匹配逻辑里处理的新状态，把一次纯粹的缺陷修复变成行为变更。
- **顺序必须保持**：`gather` 按传入顺序返回结果（不是完成顺序），故 `candidates[i]` 与 `embs[i]` 的对应关系天然成立，FAISS 索引位与 `candidates` 下标仍一一对应。这是排序结果不变的前提，要写进测试。

### D3 删同步版 `find_best_match_indices`，保留 `embed_input`

改造后 `find_best_match_indices` 零调用方——业务函数没人用就是死代码，删。

`embed_input`（同步版 embedding 原语）**保留**，尽管它也随之没有生产调用方了。理由是它承载着 `test_sync_version_is_not_cancellable_by_design` 这条**可执行的反面证据**——"同步调用在 `asyncio.wait_for` 下取消不掉"这个反直觉结论，是整条 guardrail 存在的理由。删掉函数，那条测试也就没了，结论会退化成只活在文档里的一句话。留一个 4 行的 provider 原语换一条护栏的可执行证据，划算。

> 这是本设计里最主观的一条，reviewer 若认为"零调用方就该删干净"，可以翻掉——代价是那条测试与它守的知识一起消失。

同时**修正 `embed_input` docstring 里那句错话**："本函数只应用于确实不在事件循环关键路径上的同步调用点，如 `find_best_match_indices`"——那个例子恰恰是反例，正是本次缺陷的源头。改为明确写"当前无生产调用方；保留作为异步版存在理由的对照"。

### D4 只异步化沾 embedding 的三个方法

| 方法 | 是否改 async | 理由 |
|---|---|---|
| `filter_technicians_by_preference` | ✅ | 直接调 `find_best_match_indices` |
| `find_similar_available_technician` | ✅ | 同上 |
| `find_technician_with_thought` | ✅ | 调用上面两个 |
| `parse_time_and_duration` | ❌ | 纯字符串/时间解析，无 I/O |
| `filter_technicians_by_gender` | ❌ | 纯列表过滤 |
| `find_specific_technician` / `find_available_technician` | ❌ | 只做本地 SQLite 查询（毫秒级） |

"能不改就不改"：每多一个 async 方法就多一处调用方要跟着改，而本地 SQLite 与远程 HTTP 不是同一量级的问题。若将来 DB 换成远程库，那是另一次改造。

### D5 回归测试用"心跳不停"范式，且必须带 `pytest-timeout`

沿用 `test_embedding_timeout.py` 已验证过的做法：注入永不返回的 fake embeddings，起一个心跳协程，断言心跳全跑完 → 证明循环没被占住。

`@pytest.mark.timeout` 不是可选装饰：**把实现改回同步后，这类用例不会失败而会挂死**——事件循环被冻住，连它们自己的 `asyncio.wait_for` 定时器都跑不了，任何基于 asyncio 的超时都失效。`pytest-timeout` 走线程/信号，能把"挂死"变成"明确失败"。这一点上一次已用变异验证过，本次沿用。

三条断言分工：
1. **不阻塞**：候选向量化挂起期间心跳照常推进（核心）。
2. **并发**：N 个候选只经历约 1 轮延迟而非 N 轮（防止有人"异步化"成 `for c in candidates: await aembed_input(c)`——那样不阻塞循环但延迟依旧 N 倍）。
3. **排序不变**：给定固定向量，改造前后返回的索引序列一致（防止行为漂移）。

## Risks / Trade-offs

- **[async 传染，遗留路径可能漏改]** → `find_technician_with_thought` 有两个调用方，漏掉任一个会得到一个未 await 的协程对象（真值恒为 True，可能悄悄"成功"返回一个假技师）。缓解：两处都改并被测试覆盖；`tests/test_appointment_agent.py` 与 `tests/test_harness_tools.py` 会因签名变化直接失败，跑一次全量即可暴露。
- **[并发放大瞬时压力]** → N 个候选同时打 embedding 网关，可能触发限流。缓解：N 是"门店技师数"，量级在个位到几十；且改前那 N 次也要发，只是摊在更长时间里。真遇到限流再加信号量，不预先复杂化。
- **[fake 打桩要跟着改 async]** → `tests/test_harness_tools.py:80` 的 `FakeFinder` 替换的是同步方法。缓解：一并改，且这本身就是"契约变了"的正确信号。

## Migration Plan

1. 先加 `afind_best_match_indices` 并单测（旧同步版仍在，可对照验证排序一致）。
2. 改 `TechnicianFinder` 三个方法 + 两个调用方。
3. 删同步版 `find_best_match_indices`，修 `embed_input` docstring 里的错误例子。
4. 补"心跳不停"回归测试，跑全量。

**回滚**：单分支 `git revert` 即可；无数据侧动作。

## Open Questions

- 技师专长向量是否值得缓存/持久化（那两个没人用的 `save/load_technician_embeddings` 是不是就为此准备的）——留待后续独立评估，见 Non-Goals。
