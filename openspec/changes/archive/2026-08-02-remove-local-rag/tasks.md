## 1. 先立接缝（旧实现仍在，可单独验证）

- [x] 1.1 新建 `services/knowledge_search.py`：`KnowledgeSearchPort` Protocol（`async def search(query, top_k=3, category=None) -> list[dict]`）、异常 `KnowledgeBackendNotConfigured`、缺省实现 `NotConfiguredKnowledgeSearch`（`search` 抛该异常，消息明确写"知识库尚未接入：本地 RAG 已移除，远程 RAG 未配置"）、以及 `get_knowledge_search()` / `set_knowledge_search()` 解析与注入函数（模块级 override，测试用 monkeypatch/setter 注入，对齐 conftest 既有打桩范式）。
- [x] 1.2 改 `harness/tools/knowledge.py` 的 `_handler`：改为把已校验 args 转交 `get_knowledge_search().search(...)`，删掉"懒初始化 + `getattr(service, 'initialized', False)`"那段。`search_knowledge` 的 `name` / `description` / `args_schema` / `dangerous` **一字不改**。
- [x] 1.3 新增测试 `tests/test_knowledge_search_port.py`（8 条全绿）：① 缺省端口下调用 `search_knowledge` 时异常经 agent loop 的 `_dispatch` 吞成以 `TOOL_FAILURE_PREFIX` 开头的 observation、loop 继续（不冒泡）；② 注入返回固定文档的 fake 端口后工具正常返回该列表；③ 工具四要素与 `dangerous=False` 不变（防回归）；④ 同一输入两次调用结果相同（离线确定性）。
- [x] 1.4 只跑这几项相关测试确认接缝可用（此时旧 `KnowledgeService` 仍在、未被引用）。✅ `uv run pytest tests/test_knowledge_search_port.py` → 8 passed

## 2. 删除本地 RAG 实现

- [x] 2.1 抄录 `KnowledgeService.default_knowledge` 的 10 条门店文档到本文件附录 A（营业时间/服务项目与价格/技师信息/门店地址/4 条服务介绍/预约政策/会员服务），供将来给独立 RAG 灌初始数据——这是本次唯一值得留存的数据资产。
- [x] 2.2 删 `services/knowledge_service.py`；从 `services/__init__.py` 摘除 `KnowledgeService` 导出（**`text_embedding` 的 5 个导出全部保留**——技师专长匹配在用，见 design D5）。
- [x] 2.3 删 `db/repositories/knowledge_repository.py`；从 `db/repositories/__init__.py`、`db/__init__.py`（导入 + `__all__`）、`db/db_router.py`（`knowledge_repo` 字段、`knowledge` property、`KnowledgeDBRouter` 兼容类）摘除接线；核查并清理 `db/base/interfaces.py`、`db/local_db.py` 的知识库部分。
- [x] 2.4 删 `db/models.py` 的 `KnowledgeDocument` 模型定义（**不删 SQLite 里已存在的表、不做数据迁移**，见 design D6）。
- [x] 2.5 **不动** `pyproject.toml` / `uv.lock`：`faiss-cpu` 与 `numpy` 都还有活用途（`services/text_embedding.py` 的 `IndexFlatL2` 做技师专长匹配），见 design D7。
- [x] 2.6 **不动** `config/model_provider.py`（CLAUDE.md 保护对象）、`services/text_embedding.py`、`.env.example` 的 `EMBEDDING_*`（工厂仍有活调用方，加注反而误导）。

## 3. 删除知识库管理入口

- [x] 3.1 删 `api/knowledge.py`；从 `api/__init__.py` 摘除 `knowledge_router` 的导入与 `api_routers` 列表项。
- [x] 3.2 删 `web/templates/knowledge_management.html`；删 `web/routes.py` 的 `/knowledge` 页面路由；清理 dashboard/统计路由里对 `api.knowledge.get_all_knowledge` 的调用与 `knowledge_count` / `categories` / `knowledge_documents` 等模板变量（约 `web/routes.py:68-86`、`:159-172`、`:196-207`）。
- [x] 3.3 删 `web/templates/index.html` 里跳 `/knowledge` 的导航按钮；核查其余模板是否引用已清理的模板变量（避免 Jinja 渲染报 undefined）。
- [x] 3.4 删 `app.py` 的 `KnowledgeService` 导入与启动时的知识库初始化（`app.py:17`、`:54-55`）；核查 `KnowledgeRequest` 模型（`app.py:37`）是否还有用，无用则删。

## 4. 删除 pre-harness 咨询旧链路（含 BREAKING）

- [x] 4.1 删 `agents/consultant/`（整个目录：`knowledge_retriever` / `prompt_builder` / `consultation_classifier` / `response_generator` / `consultation_processor` + `__init__.py`）与 `agents/consultant_agent.py`；从 `agents/__init__.py` 摘除 `ConsultantAgent`。
- [x] 4.2 删 `api/consultation.py`；从 `api/__init__.py` 摘除 `consultation_router` 与 `api_routers` 列表项。**BREAKING：`/api/consultation` 端点下线**——人审若要保留该端点，改由 harness 的 consultant 子 Agent 承接（另开变更，不塞进本次）。
- [x] 4.3 确认 `harness/subagents/consultant.py` 与 `api/chat_handler.py` 的主对话路径完全不受影响（前者只引用工具名 `search_knowledge`，后者不调旧链路）。
- [x] 4.4 **不动** `agents/appointment/technician_finder.py`：它虽用 `services/text_embedding.py` 的 `find_best_match_indices`（embedding+FAISS），但那服务的是技师专长匹配而非知识库，且在 `find_technician` 的活路径上（见 design D5/D8）。确认删除动作没有牵连到它、`find_technician` 工具仍可用。

## 5. 测试同步

- [x] 5.1 删 `tests/test_consultant_agent.py`（被测对象已删）。
- [x] 5.2 `tests/test_embedding_timeout.py` **只删 1 条**：`test_knowledge_search_does_not_block_the_loop`（唯一依赖 `KnowledgeService` 的用例）。其余 10 条全部保留——被测主体（embedding 客户端 + `aembed_input`）都还在。在文件 docstring 记一笔：原先由这条用例覆盖的"真实调用链不冻住事件循环"，在知识库路径移除后暂无等价覆盖；技师路径存在同类缺陷但属独立任务（见 design D8）。
- [x] 5.3 改 `tests/conftest.py` 的 `fake_llm_env`：只摘除 `agents.consultant_agent` 打桩。**保留** `services.text_embedding.create_embedding_model` 的打桩与 `_FakeEmbeddings`——技师专长匹配仍会走到它，摘掉会让测试触网。
- [x] 5.4 逐一处理其余引用被删对象的测试（`tests/test_harness_tools.py`、`test_tool_registry.py`、`test_subagents.py`、`test_guardrails_permission.py`、`test_slot_recovery.py`、`test_agent_loop_tool_timeout.py`、`test_eval_trace_collect.py`、`test_eval_task_success.py`、`test_triage.py`）：对 `KnowledgeService` 的打桩改为注入 fake 端口；仅用 `search_knowledge` 作"任一只读工具"样例的用例保持不变（工具契约未变，应当零改动——若需改动即说明契约被破坏，回头修 1.2）。
- [x] 5.5 `evals/cases.jsonl` 与 `evals/baseline.json` **一行不改**（`git diff --stat` 复核这两个文件不出现在改动列表里）。

## 6. 文档同步

- [x] 6.1 `CLAUDE.md`：改"不要重写：`services/`、`db/`、`config/model_provider.py`、RAG（SQLite+FAISS）"这条——本地 RAG 已删除，改为记"知识库检索走 `services/knowledge_search.py` 的端口，待接入独立 RAG 项目"。
- [x] 6.2 `openspec/project.md`：`:18` 技术栈里的 FAISS 改为标注"仅用于技师专长相似度匹配，知识库 RAG 已移除"；`:25` 五层结构删掉"外加 RAG（FAISS+SQLite）"；`:42` "不要重写"清单里的 RAG 改为端口说法；`:35` 那条"同步 SQLite / FAISS 阻塞掐不断"的工具超时告警**原样保留**——它现在正好命中技师路径的真实缺陷（design D8）。
- [x] 6.3 `README.md`：项目简介（`:3`）、功能列表里的 RAG/Embedding 缓存/知识库数据管理（`:17`/`:21`/`:22`）、咨询 Agent 与其流程图（`:75`/`:78`/`:84`）、`:126` 的"为什么用 RAG"设计说明——统一改为"知识库检索已外移，本仓只留工具契约"。
- [x] 6.4 `RUNNING.md`：`:19` 的 `faiss-cpu` 安装提示与 `:27-38`/`:143` 的 `EMBEDDING_*` **原样保留**（依赖与配置都还在用）；只需在 `.env` 说明段点明 embedding 现在服务的是技师专长匹配，不再有知识库检索。
- [x] 6.5 `docs/agent-eval-fieldguide.md`：§5.5（`:446`）改为"本地 RAG 已移除，`search_knowledge` 现为端口契约"；§11 改造 5 的暂缓说明（`:463`/`:465`/`:661`）与 §12 速查表（`:616`）、§13 文件索引（`:791`）同步——把"待迁移后再评"更新为"本地实现已删、组件级检索评估随 RAG 外移，端到端贡献仍留 Agent 侧"。
- [x] 6.6 `docs/harness-code-reading.md`：`:308-321` 的 `search_knowledge` 薄封装讲解改为经端口转交（那段"换检索实现时工具层一行都不用动"的论断正好被本次变更验证，可点明）。
- [x] 6.7 `docs/harness-refactor-plan.md`：`:26` 的"保留 RAG 的 SQLite+FAISS 基础"、`:96` 的 `search_knowledge → KnowledgeService` 同步更新。
- [x] 6.8 `evals/README.md`：加一段"`任务成功率` / `回复质量通过率` 的下探源自知识库未接入（`search_knowledge` 恒以'未接入'失败收场），**非模型能力退化**；门禁两项指标不受影响、基线无需重定"——记法对齐上一切片"F1 上涨纯属构成变化"。同时写明**解耦只覆盖 `query` 类**：`appointment` 类仍会经技师专长匹配打 embedding 网关，网关抽风时该类指标依然会失真（design D8）。
- [x] 6.9 `docs/skills-notes.md:108` 顺手更正"已有 SQLite+FAISS"的过期表述。

## 7. 验证与收尾

- [x] 7.1 `uv run pytest` 全绿——成功静默、只报错。特别确认：`search_knowledge` 相关的工具层/registry/子 Agent 测试**零改动通过**（契约未破的证据）。
- [x] 7.2 起服务冒烟：主对话路径可用；咨询类提问得到"知识库未接入"的如实回复而非编造答案；`/knowledge` 与 `/api/consultation` 已下线且首页无死链。
- [x] 7.3 `git diff --stat` 复核这几个文件均未被改动：`evals/cases.jsonl`、`evals/baseline.json`、`config/model_provider.py`、`services/text_embedding.py`、`agents/appointment/technician_finder.py`、`pyproject.toml`、`uv.lock`。
- [x] 7.4 **不跑** `--update-baseline`（本变更不重定基线，理由见 design D3）；可选跑一次 `--gate` 复核门禁仍绿（门禁两项与知识库无关，应当不动）。
- [x] 7.5 更新记忆：`rag-eval-deferred`（本地实现已删、端口已立、剩下的是接远程 client；解耦只覆盖 `query` 类）、`eval-progress-state`（`任务成功率`/`回复质量` 下探的新归因）、`eval-baseline-blocked-on-rag`（挂起分支的恢复前置条件从"RAG 修好"变为"远程 RAG 接入并注入端口"）。

## 附录 A · 待抄录的 10 条默认知识库文档

> 由 task 2.1 在删除 `services/knowledge_service.py` **之前**抄录（源：该文件的 `default_knowledge`，
> 每条含 `content` / `category` / `keywords`），供将来给独立 RAG 项目灌初始数据。

| # | category | content | keywords |
|---|---|---|---|
| 1 | 营业时间 | 我们推拿房的营业时间是每天上午9点到晚上10点，全年无休。 | 营业时间, 开门, 关门, 几点, 时间 |
| 2 | 服务项目 | 我们提供多种推拿服务：全身推拿（120元/60分钟）、肩颈推拿（80元/30分钟）、足底按摩（100元/45分钟）、背部推拿（90元/40分钟）。 | 服务, 推拿, 按摩, 价格, 收费, 多少钱 |
| 3 | 技师信息 | 我们有专业的男女技师为您服务。所有技师都经过专业培训，持有相关资格证书。您可以根据个人喜好选择男技师或女技师。 | 技师, 师傅, 男, 女, 专业, 资格 |
| 4 | 门店地址 | 我们店的位置位于北京海淀区中关村大街27号，交通便利，地铁2号线A口向北步行100米即可到达 | 地址, 门店信息, 到达方式, 交通 |
| 5 | 服务介绍 | 全身推拿能够舒缓全身肌肉疲劳，促进血液循环，缓解压力。特别适合久坐办公室的上班族和体力劳动者。 | 全身推拿, 效果, 作用, 好处, 适合 |
| 6 | 服务介绍 | 肩颈推拿专门针对颈椎和肩部问题，能有效缓解颈椎疼痛、肩膀僵硬等问题。特别推荐给长期使用电脑的人群。 | 肩颈推拿, 颈椎, 肩膀, 疼痛, 僵硬 |
| 7 | 服务介绍 | 足底按摩通过刺激足部穴位，能够调节全身气血运行，缓解疲劳，改善睡眠质量。 | 足底按摩, 脚, 穴位, 睡眠, 疲劳 |
| 8 | 服务质量 | 我们的技师都有3年以上的专业经验，定期接受培训以确保服务质量。我们注重客户体验，力求为每位客户提供最舒适的服务。 | 经验, 专业, 培训, 质量, 舒适 |
| 9 | 预约政策 | 如需取消或更改预约，请提前至少2小时通知我们。临时取消可能会产生一定的费用。 | 取消, 更改, 改期, 退约, 政策 |
| 10 | 会员服务 | 我们提供会员卡服务，充值500元送50元，充值1000元送150元。会员还可享受预约优先权和生日优惠。 | 会员, 充值, 优惠, 折扣, 生日 |

⚠ 注意：第 2 条的价格与第 10 条的充值档位是**评估用例的事实依据**——`evals/cases.jsonl` 里
`query` 类问价格的用例，其"正确回答"以这份内容为准。将来给独立 RAG 灌数据时若改动这些数字，
`回复质量通过率` 的 judge 判定会随之变化。
