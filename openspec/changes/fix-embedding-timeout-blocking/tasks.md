# 任务清单：修复向量化调用无超时且阻塞事件循环

## 1. 超时落到实处（第一步：挂死从「永久」降为「至多 N 秒」）

- [ ] 1.1 `config/model_provider.py` 的 `create_embedding_model()` 增加可选 `timeout` 参数，缺省取 `EMBEDDING_TIMEOUT_SECONDS`（缺省 **20**）；`OpenAIEmbeddings` 与 `AzureOpenAIEmbeddings` 两条路径都传。**只加参数，不改 Provider 抽象的其余部分**（保留资产）
- [ ] 1.2 `services/text_embedding.py` 的 `embed_input` 把 `timeout` **真正透传**给 `create_embedding_model()`，并把缺省值从 600 改为与环境变量一致；删掉签名里没人用的 `model` / `encoding_format` / `dimensions` 装饰参数**或**在 docstring 里明确标注它们当前不生效（二者择一，不要留下第二个「签名里的谎言」）
- [ ] 1.3 `.env.example` 增加 `EMBEDDING_TIMEOUT_SECONDS`，注释写明「向量化是秒级操作；底层客户端默认 600s 等于没有上限」
- [ ] 1.4 单测：断言构造出的嵌入客户端确实带上了配置的超时值（不触网，只检查实例属性）

## 2. 异步路径（第二步：事件循环不再被冻住）

- [ ] 2.1 `services/text_embedding.py` 新增 `async def aembed_input(...)`，走 LangChain 原生 `aembed_query`（已确认 `OpenAIEmbeddings` 提供）。**不用 `asyncio.to_thread`**——线程里的同步调用依然不可取消，超时后线程仍在后台跑到结束，连接与线程都泄漏（见 design D2）
- [ ] 2.2 同步 `embed_input` 与新的 `aembed_input` 在各自 docstring 里**互相指明**：async 上下文必须用异步版；同步版仅供 `find_best_match_indices` 这类不在事件循环关键路径上的调用点
- [ ] 2.3 `services/knowledge_service.py` 把 **6 处** `async def` 内的 `embed_input(...)` 改为 `await aembed_input(...)`：`search`（热路径）、`initialize`、`_create_default_knowledge`、`_build_vector_index`、`add_document`、`update_document`
- [ ] 2.4 核对无遗漏：`grep -n "embed_input" services/` 逐一确认 `async def` 内不再有同步调用，且同步调用点（`find_best_match_indices`）保持不变

## 3. 测试（两个缺陷分别守住）

- [ ] 3.1 注入永不返回的 fake 嵌入实现，断言调用在超时内**以失败收场**而非无限期挂起（守「有超时」）
- [ ] 3.2 断言**等待期间事件循环仍能推进**：另起一个协程，验证它在嵌入调用挂着的同时按时被调度（守「不阻塞」）。这条是本变更的核心断言——它才真正区分两个缺陷
- [ ] 3.3 断言超时留痕：失败时记 ERROR 日志且 `KnowledgeService.search` 按既有路径降级，不静默返回空而无记录
- [ ] 3.4 回归：同步 `embed_input` 行为不变（`find_best_match_indices` 相关测试仍绿）
- [ ] 3.5 全程离线确定性——不触网、不产生分钟级真实等待

## 4. 验证与收尾

- [ ] 4.1 `uv run pytest` 全绿
- [ ] 4.2 **端到端证据**：重跑 `uv run python evals/run_evals.py --samples 3`，确认能跑完而不再挂死（当前该跑批因本缺陷连续两次卡死；跑完本身就是本变更奏效的证明）。若 embedding 模型仍不可用，检索会快速失败但**不再挂起**——这正是本变更要的行为
- [ ] 4.3 若 4.2 跑通，顺带用 `--gate` 重跑一次门禁，补上已归档 change `feishu-channel-integration` 的 tasks 4.2 中标注为「当前无法重跑」的那一项（在本 change 的记录里注明即可，不回改已归档文件）
- [ ] 4.4 在 design 的 Open Questions 里回填 `EMBEDDING_TIMEOUT_SECONDS` 缺省值的实测依据（若网关恢复可用则观察一次正常延迟分布；否则如实标注「未能观察，按量级推定」）

## 5. 明确不做（记录以防范围漂移）

- [ ] 5.1 确认**未**引入嵌入客户端复用/单例或结果缓存——那是性能优化，与「不能挂死」是两件事（见 design D4）。本项为自查项，勾选表示已确认没做
- [ ] 5.2 确认**未**改 RAG 检索逻辑、未动 SQLite+FAISS 基础、未重写 `KnowledgeService` 任何业务规则（保留资产约束）
- [ ] 5.3 确认**未**试图修复「`text-embedding-3-small` 在当前网关不可用」——那是独立的配置问题，与本变更正交
