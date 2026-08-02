## Context

本地 RAG 目前是一条完整的纵向切片：`harness/tools/knowledge.py`（工具）→ `services/knowledge_service.py`（SQLite 取文档 + FAISS 内积检索 + 调远程 embedding）→ `services/text_embedding.py`（embedding client）→ `db/repositories/knowledge_repository.py`（`KnowledgeDocument` 表）。此外还挂着两条旁支：`api/knowledge.py` + `web/templates/knowledge_management.html`（知识库增删改查后台），以及 pre-harness 的咨询链路 `api/consultation.py` → `agents/consultant_agent.py` → `agents/consultant/knowledge_retriever.py`。

约束与既有事实（决定了本设计的形状）：

1. **`search_knowledge` 的名字被三处"外部"引用**：`harness/subagents/consultant.py` 的工具切片（唯一工具）、`openspec/specs/subagent-delegation/spec.md` 的需求、以及 `evals/cases.jsonl` 里 38 条用例（36 条作为 `expected_outcome`）。改名或删名的成本远大于换实现。
2. **门禁只守 `{工具调用-F1, 槽位抽取完整率}`**，两项都只量"有没有调对工具、抽对槽位"，与工具返回什么无关（2026-07-30 已实测确认的门禁盲区：RAG 整段坏掉期间门禁一路 PASS）。这次这个盲区反而是有利条件——只要工具契约不变，`evals/baseline.json` 不必重定。
3. **`evals-dataset-scaleup-v2` 正因基线挂起**（184 条新数据集 + 旧基线不可混用），所以本变更 MUST NOT 触碰 `evals/cases.jsonl` 与 `evals/baseline.json`，否则会把两个挂起问题缠在一起。
4. **agent loop 已有单工具失败回灌机制**：`harness/runtime/agent_loop.py:322` 把工具异常吞成 `"工具执行失败（{name}）：{exc}"` 作为 observation 回灌，`evals/trace_collect.py:89` 据 `TOOL_FAILURE_PREFIX` 判定 `ok`。

## Goals / Non-Goals

**Goals:**
- 删掉本地 RAG 的全部实现与其专属入口，使 Agent 侧不再依赖 embedding 网关的可用性。
- 把知识库检索收敛成**一个可替换的端口**，将来接入独立 RAG 项目只需实现并注入一个 client。
- 让"未接入"这件事在指标上**如实呈现**，不制造虚假的成功。
- 零改动 `evals/cases.jsonl` 与 `evals/baseline.json`，不与挂起的基线纠缠。

**Non-Goals:**
- 不实现远程 RAG client（独立 RAG 项目尚未就绪）；本次只留端口与"未接入"缺省实现。
- 不做数据迁移：SQLite 里既有的 `knowledge_documents` 表数据不导出、不删表（见 D6）。
- 不重定基线、不动评估数据集。
- 不改 `search_knowledge` 的 `name` / `description` / `args_schema` / `dangerous`。
- **不动 embedding 基础设施**：`services/text_embedding.py`、`config/model_provider.py`、`faiss-cpu`、`numpy` 全部保留——技师专长相似度匹配还在用（见 D5）。
- **不修技师路径上的事件循环阻塞缺陷**，也不把技师匹配去 embedding 化——那是独立取舍，已单列为后续任务（见 D8）。

## Decisions

### D1 端口放在 `services/`，而非 `harness/`

新增 `services/knowledge_search.py`：一个 `KnowledgeSearchPort` Protocol（`async def search(query, top_k, category) -> list[dict]`）、一个缺省实现 `NotConfiguredKnowledgeSearch`、以及 `get_knowledge_search()` / `set_knowledge_search()` 这对解析与注入函数。

**为什么不是 `harness/tools/knowledge_port.py`**：项目的既有口径是"工具是 `services/` 的薄封装"（写在 `harness/tools/base.py` 的模块 docstring 与 `openspec/project.md` 里），单向依赖分层也是 `harness/` → `services/`。把出站适配器放进工具层会让工具层同时承担"薄封装"和"外部集成"两个角色，破坏这条口径；将来远程 RAG client 落在 `services/` 也与 `text_embedding.py` 原先的位置一致。

`harness/tools/knowledge.py` 的 handler 因此只是把校验过的 args 转交 `get_knowledge_search().search(...)`——比现在还薄（不再需要那段"懒初始化 + `getattr(service, 'initialized', False)` 容错"）。

### D2 "未接入"走既有的工具失败回灌路径，而不是返回一个"看起来成功"的结果

`NotConfiguredKnowledgeSearch.search()` 抛一个专用异常 `KnowledgeBackendNotConfigured`，消息明确写"知识库尚未接入（本地 RAG 已移除，远程 RAG 未配置）"。`_dispatch` 会把它吞成 `"工具执行失败（search_knowledge）：知识库尚未接入…"` 回灌给模型，loop 继续。

考虑过的两个替代方案，都更差：

- **返回空列表 `[]`**：模型会把它读成"查过了、库里没有这条信息"，进而**凭训练知识编造价格与政策**——这恰是 `harness/subagents/consultant.py` 的 system prompt 明令禁止的（"检索结果不足以回答时，如实说明，不要编造"）。而且 `guardrails` 里已有一条硬约束："MUST NOT 静默返回空结果而不留痕"。
- **返回 `{"available": false, "message": ...}` 这类结构化 dict**：模型能读懂，但 `evals/trace_collect.py` 判 `ok` 只看结果是否以 `TOOL_FAILURE_PREFIX` 开头，于是这次调用会被记成**执行成功**，`任务成功率` 把"根本没检索到"算作达成业务终态。指标撒谎比指标下探糟得多——本项目一路的口径都是"不伪造分母、宁可显式 N/A / 显式失败"。

抛异常还有一个附带好处：`harness/observability/trace_signals.py` 的 `tool_failure` 坏信号会正常点亮，`evals/triage.py` 的在线闭环能把这些 case 甄别出来，"未接入"这件事在可观测面上是**看得见的**，而不是悄悄地把咨询类回答降级。

### D3 保住工具契约，代价全部落在两个非门禁指标上

`name` / `description` / `args_schema`（`SearchKnowledgeArgs`，含 `query` / `top_k` / `category`）/ `dangerous=False` 一律不变。于是：

| 面 | 影响 |
|---|---|
| `工具调用-F1`（门禁） | **零影响**——工具仍注册、仍被模型调用、仍匹配用例标注 |
| `槽位抽取完整率`（门禁） | **零影响**——与知识库无关 |
| `任务成功率`（非门禁） | `query` 类的 36 条 `expected_outcome` 会判失败 → 该类掉到 0；宏平均随之下探 |
| `回复质量通过率`（非门禁） | 咨询类回复变成"如实告知未接入"，judge 大概率判不通过 |
| `evals/baseline.json` | **不需重定**（门禁两项不动） |

后两项在 RAG 故障期本来就是废数（`回复质量` 恒 N/A、`任务成功率` 被压到 20.8%），现在从"随网关抽风而随机失真"变成"确定性地为 0"——**从不可解释的噪声变成可解释的已知缺口**，这是改善而非退步。接入独立 RAG 后这两项才第一次有真实可比的读数。

### D4 pre-harness 咨询旧链路整条删除，而不是留桩

`agents/consultant_agent.py` + `agents/consultant/` 五个组件 + `api/consultation.py` 这条链路的**全部价值就是"拿本地 RAG 结果生成咨询回复"**，Phase 3 之后主对话路径走 `api/chat_handler.py` → agent loop，咨询能力由 `harness/subagents/consultant.py` 承担。删掉本地 RAG 后，留着它只能是一条永远返回"未接入"的死链路，还要为它维护一套 fake 打桩（`tests/conftest.py` 的 `fake_llm_env` 里就有它）。

**BREAKING**：`/api/consultation` 端点下线。这是设计里唯一的对外行为收缩，故在 proposal 与 tasks 里都单列，便于人审时否决——若要保留该端点，替代方案是让它也走 harness 的 consultant 子 Agent（那是另一个变更的范围，不塞进本次）。

`agents/appointment/technician_finder.py` 出现在"引用 knowledge"的搜索结果里，但那是它自己的技师检索用词，与知识库无关，**不动**。

### D5 embedding 基础设施整体保留：它不只服务知识库

**实现期修正**（原设计误判，此处记录事实与更正）：起草时只核查了"谁 import numpy / faiss"，漏查"谁 import `services/text_embedding.py`"。真实情况是 `agents/appointment/technician_finder.py:9` 用它的 `find_best_match_indices` 做**技师专长相似度匹配**，而那是 embedding + FAISS + numpy 的另一处用途，且在 `find_technician` 工具的**活路径**上（`harness/tools/technician.py:39` → `find_technician_with_thought`），两个触发点：

- `technician_finder.py:242` `filter_technicians_by_preference`——只要用例带力度偏好就必走（预约类多数用例都带）；
- `technician_finder.py:98` `find_similar_available_technician`——指定技师不可用时找相似技师。

故删除面收窄为"知识库那条纵向切片"：**保留** `services/text_embedding.py`、`config/model_provider.py`、`faiss-cpu`、`numpy`、`.env.example` 的 `EMBEDDING_*`（它们仍有活调用方，加注反而会误导）。

连带影响：`guardrails` 的「外部调用超时与非阻塞」需求**无需任何改动**——客户端构造与异步调用方都还在，主体完整。`tests/test_embedding_timeout.py` 只删 1 条（`test_knowledge_search_does_not_block_the_loop`，依赖 `KnowledgeService`），其余 10 条全部保留，那条从实测缺陷反推出的护栏继续被测试守住。

### D8 收益是部分的，且技师那条路径上还压着一个已确认的缺陷

必须诚实记账：本次把 `query` 类彻底与 embedding 网关解耦，但 `appointment` 类**没有**——带偏好的预约仍会打网关。所以"Agent 评估不再被 RAG 可用性绑架"这个收益本次只兑现一半。

更糟的是，实现期核查该路径时确认了一个**独立的、已存在的缺陷**：`harness/tools/technician.py:18` 的 handler 是 `async`，却同步调用下去，最终在 `services/text_embedding.py:20` 执行 `[embed_input(c) for c in candidates]`——**每个候选一次同步阻塞 HTTP**（加查询共 N+1 次，每次上限 20 秒）。`embed_input` 自己的 docstring 就写明"在 async 上下文里请用 `aembed_input`，否则占住整个事件循环"。这正是归档 change `fix-embedding-timeout-blocking` 修的缺陷，当时只修了知识库那条路径、技师这条漏了，且它**违反现行的** `guardrails`「async 上下文 MUST NOT 执行同步阻塞 I/O」。

该缺陷**不在本次范围内**（它与知识库无关，修它要动技师匹配的调用链，是独立取舍），已单列为后续任务。本设计只负责把它记清楚，避免"删了 RAG 就以为解耦完成了"的错觉。

### D6 不做数据迁移：删映射，不删表

删除 `db/repositories/knowledge_repository.py`、`db/models.py` 的 `KnowledgeDocument`、以及 `db/__init__.py` / `db/db_router.py`（`knowledge` 属性 + `KnowledgeDBRouter` 兼容类）里的接线。SQLite 文件里已存在的 `knowledge_documents` 表**不删、不导出**：删掉 ORM 映射后它就是一张无人引用的静态表，占用可忽略；而知识库内容的真正来源将是独立 RAG 项目，导出这 10 条默认文档没有价值。`KnowledgeService.default_knowledge` 里那 10 条门店信息（营业时间/价格/地址/会员政策等）**在删除前抄录进 tasks 的附录**，供将来给独立 RAG 灌初始数据时参考——这是本次唯一值得留存的数据资产。

### D7 依赖不动：`faiss-cpu` 与 `numpy` 都还有活用途

`numpy` 被 `services/knowledge_service.py` 与 `services/text_embedding.py` 用到、`faiss` 被这两个文件都用到（前者 `IndexFlatIP` 做知识检索、后者 `IndexFlatL2` 做技师专长匹配）。删掉前者后，后者仍在（见 D5），故 `pyproject.toml` 的 `faiss-cpu>=1.7.0` 与 `numpy>=1.21.0` **保留**，`uv.lock` 不动。

## Risks / Trade-offs

- **[咨询类能力在过渡期实质下线]** → 这是删除本地 RAG 的直接后果，不可回避。缓解：模型会拿到明确的"未接入"说明并如实告知用户，而不是编造答案（D2）；`harness/subagents/consultant.py` 的 prompt 已有"不要编造价格或政策"的约束，二者叠加。
- **[两个非门禁指标确定性变差，可能被误读为回归]** → 缓解：在 `evals/README.md` 与 `docs/agent-eval-fieldguide.md` 显式记一笔"`任务成功率` / `回复质量通过率` 的下探源自知识库未接入，非模型能力退化"，与上一切片"F1 上涨纯属构成变化"的记法同构。
- **[`/api/consultation` 下线可能有未知调用方]** → 缓解：单列为 BREAKING 交人审；`web/` 前端与 `api/chat_handler.py` 均不调它（已查），风险主要是外部脚本。
- **[删得过深，将来接远程 RAG 要重建的东西变多]** → 缓解：端口 + Protocol 就是为此留的接缝；契约（工具四要素 + 端口签名 + 评估用例标注）全部保留，重建面只有"一个 client 实现 + 注入点 + 一条超时测试"。
- **[解耦收益只兑现一半，可能被当成已完成]** → `appointment` 类仍打 embedding 网关，且那条路径上压着一个会冻住事件循环的已确认缺陷（D8）。缓解：proposal 的 Impact、design D8、以及后续任务里三处都写明这个边界；`evals/README.md` 的归因说明也只声明 `query` 类解耦。

## Migration Plan

1. 先加端口（`services/knowledge_search.py`）并把 `harness/tools/knowledge.py` 切到端口——此时旧实现仍在，可单独验证工具行为。
2. 再删实现与旁支（services / db / api / web / agents 旧链路 / 依赖）。
3. 最后同步测试与文档。

**回滚**：本变更全部落在一个分支上，`git revert` 即可恢复；SQLite 表未删，数据侧无不可逆动作。

## Open Questions

- 独立 RAG 项目的接口形态（HTTP/gRPC、鉴权方式、返回字段）未定，故本次不预判 client 形状，只固定端口签名与 `SearchKnowledgeArgs` 的入参口径。
- `/api/consultation` 是否确有外部调用方——需人审确认（D4）。
