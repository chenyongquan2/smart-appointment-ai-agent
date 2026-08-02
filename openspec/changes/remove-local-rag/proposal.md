## Why

本地 RAG（`services/knowledge_service.py` 的 SQLite + FAISS + 远程 embedding）后续会被替换为一个**独立的 RAG 项目**，继续维护本地实现没有长期价值。更硬的理由是：它的可用性一直在**绑架 Agent 评估**——2026-07-30~08-01 期间 embedding 网关在 `503 无通道` → `403 未授权` → `200 正常` → `400 Model not exist` 之间反复，每次都让评估要么跑不动、要么让 `任务成功率` / `回复质量通过率` 变成废数（后者恒 N/A、前者被压到 20.8%）。当前 `evals-dataset-scaleup-v2` 的重定基线正因此挂起。

先删掉本地实现、只留一个**工具层契约**，能立刻把 Agent 侧与 RAG 可用性解耦；将来接入独立 RAG 只需替换契约背后的一个 client 实现。

## What Changes

- **删除本地 RAG 实现**：`services/knowledge_service.py`、`services/text_embedding.py`、`db/repositories/knowledge_repository.py` 及 `db/` 层的知识库接线（`db/__init__.py`、`db/db_router.py` 的 `knowledge` 属性与 `KnowledgeDBRouter`、`db/base/interfaces.py`、`db/local_db.py`）、`KnowledgeDocument` 模型的使用面。
- **删除知识库管理入口**：`api/knowledge.py`、`web/templates/knowledge_management.html` 及其路由与导航入口、`app.py` 里的知识库启动初始化。知识库的写入/维护随 RAG 一起外移到独立项目。
- **删除 pre-harness 的咨询旧链路**：`agents/consultant/knowledge_retriever.py` 及仅为它存在的 `agents/consultant/`、`agents/consultant_agent.py`、`api/consultation.py`、`tests/test_consultant_agent.py`。该链路是 Phase 3 之前的硬路由实现，已被 `harness/subagents/consultant.py` 取代，其唯一价值就是"拿本地 RAG 结果生成咨询回复"。**BREAKING**：`/api/consultation` HTTP 端点随之下线（主对话路径 `api/chat_handler.py` 不受影响）。
- **保留 `services/text_embedding.py`、`faiss-cpu`、`numpy`、`config/model_provider.py`**：它们不只服务知识库——`agents/appointment/technician_finder.py` 的**技师专长相似度匹配**（`find_best_match_indices`）也用 embedding + FAISS，且它在 `find_technician` 工具的活路径上。故本次删除面收窄为"知识库那条纵向切片"，embedding 基础设施整体不动（`tests/test_embedding_timeout.py` 因此只删 1 条依赖 `KnowledgeService` 的用例，其余 10 条全保留）。
- **`search_knowledge` 工具改为契约化**：`name` / `description` / `args_schema`（`SearchKnowledgeArgs`）**保持不变**，handler 从"直连 `KnowledgeService`"改为调用一个**知识库检索端口**（`KnowledgeSearchPort`）。未接入远程 RAG 时由缺省实现返回**明确的"知识库未接入"结果**——既不静默返回空列表（会被模型当成"查过了没有"而编造答案），也不抛异常崩 loop（Phase 5 的错误隔离要求单工具失败可自愈）。
- **不动的部分**：`harness/subagents/consultant.py`（其唯一工具 `search_knowledge` 仍在，最小权限设计不变）、`harness/tools/registry.py` 的注册与切片、`evals/cases.jsonl`（38 条引用 `search_knowledge`、其中 36 条 `expected_outcome`）**一条不改**，`evals/baseline.json` **不需重定**。

## Capabilities

### New Capabilities
- 无。本变更是"删实现 + 把既有工具的下游依赖换成契约"，不引入新能力。

### Modified Capabilities
- `tool-layer`（**唯一**）: 「核心工具集」里 `search_knowledge` → `KnowledgeService.search` 的映射失效。改为：`search_knowledge` SHALL 调用一个可替换的知识库检索端口；未配置远程 RAG 时 SHALL 以明确标示"知识库未接入"的失败收场（走既有的单工具失败回灌路径），而非空列表或"看似成功"的结果。工具的 `name` / `description` / `args_schema` / `dangerous=False` 均不变。
- `guardrails` 的「外部调用超时与非阻塞」**无需改动**——embedding 客户端与其异步调用方（`services/text_embedding.py`）均保留，需求主体与其测试全都还在。

## Impact

**代码**：`services/`（删 `knowledge_service.py` 1 个文件）、`db/`（删 repository + 摘除接线）、`api/`（删 2 个路由模块）、`web/`（删 1 个模板 + 导航）、`agents/`（删整个 consultant 旧链路）、`harness/tools/knowledge.py`（改 handler）、新增 `services/knowledge_search.py`（端口）、`app.py`（摘除启动初始化与路由注册）。

**测试**：删 `tests/test_consultant_agent.py`；`tests/test_embedding_timeout.py` 删 1 条依赖 `KnowledgeService` 的用例（其余 10 条保留）；改 `tests/conftest.py`（`fake_llm_env` 里的 `agents.consultant_agent` 打桩；`services.text_embedding` 的打桩保留，技师匹配仍需要它）、`tests/test_harness_tools.py` 等对 `KnowledgeService` 打桩的用例改为对契约端口注入 fake。新增：缺省端口以"未接入"失败收场、以及注入 fake 端口时 `search_knowledge` 正常返回文档的测试。

**评估**：门禁两项指标（`工具调用-F1`、`槽位抽取完整率`）**一分不动**——它们量的是"有没有调对工具、抽对槽位"，与工具返回什么无关（这正是 2026-07-30 已实测确认的门禁盲区，此处反而是有利条件）。非门禁的 `任务成功率` / `回复质量通过率` 会下探，但这两项在 RAG 故障期本就是废数。挂起分支 `feat/evals-dataset-scaleup` 的恢复路径不受影响，`query` 类恢复后可注入 fake 端口获得**离线确定性**。

⚠ **收益边界（重要）**："Agent 评估不再被 embedding 网关绑架"本次只**部分**达成：`query` 类彻底解耦，但 `appointment` 类仍会经技师专长匹配打 embedding 网关（见 Non-Goals 与 design D8）。

**文档**：`CLAUDE.md` 的"不要重写：…RAG（SQLite+FAISS）"约定已过期；另需同步 `openspec/project.md`、`docs/harness-refactor-plan.md`、`README.md`、`RUNNING.md`、`evals/README.md`、`docs/agent-eval-fieldguide.md`、`docs/harness-code-reading.md` 中涉及本地 RAG 的说法。
