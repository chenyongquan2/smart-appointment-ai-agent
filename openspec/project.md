# Project Context

> OpenSpec 项目准则（= 本项目的 constitution / 黄金准则）。OpenSpec 每次 `/opsx:propose` 都会把这里当上下文。
> 保持精简、高信号——它是"地图",细节指向下面的链接,别堆砌。

## 项目是什么

面向按摩门店场景的**智能预约与咨询系统**（多 Agent + RAG + FastAPI）。
当前正从"LLM 分类 + if/else 硬路由的 workflow"重构为真正的 **Agent Harness**。
重构总路线图见 [docs/harness-refactor-plan.md](../docs/harness-refactor-plan.md)；概念背景见 [docs/harness-index.md](../docs/harness-index.md)。

## 技术栈

- **语言**：Python `>=3.10,<3.13`
- **Web**：FastAPI + uvicorn + Jinja2（`web/` 前端模板）
- **数据校验**：Pydantic v2（结构化输出的核心）
- **LLM 编排**：LangChain 0.3.x（`langchain-openai` / `-core` / `-community` / `-experimental`）
- **向量化**：FAISS + embedding，**仅用于技师专长相似度匹配**（`services/text_embedding.py`）；知识库 RAG 已移除
- **持久化**：SQLite/SQLAlchemy
- **协议**：MCP
- **依赖管理**：**uv**（`package = false`，用 `uv run` / `uv sync`，不要用 pip）
- **测试**：pytest（`tests/`）

## 架构与分层

分层结构：`Channel/Gateway(channels/ + web/)` → `Executor(executor/ 任务执行层)` → `Harness(harness/ 域无关运行时)` → `Domains(domains/ 可装载领域包)` → `Services(services/)` → `DB(db/ Repository)` → `Config(config/, 含 model_provider Provider 抽象)`。知识库检索是一个**出站端口**（`services/knowledge_search.py`），实现将由独立的 RAG 项目提供。

**换域 = 换五样东西**（change `domain-packages`）：工具集 + 子 Agent 集 + 系统提示 + 权限策略 + **评估数据与标注口径**。这五样在 `domains/<name>/`，由 `AGENT_DOMAIN` 环境变量决定装哪个（缺省 `appointment`）。运行时（TAO 循环、记忆、护栏、Tracer、评估运行器）**一行不动**，且 MUST NOT 出现 `if domain == ...`。

第五样不止是一个数据目录：评估机制要读用例，就得知道「本域的标签叫什么、哪些入参算槽位、本域能守哪些门禁项」，这三项由 `EvalProfile` 声明（change `oncall-evals-bootstrap`）。它们此前硬编码在 `evals/` 里，装上另一个域要么直接加载失败，要么门禁**静默**少守一项。

判断一段代码该放哪，只问：**换成另一个域还成立吗？** 成立 → 域无关，留 `harness/` 或 `evals/`；不成立 → 进领域包。这条判据有测试守着（`tests/test_domain_loading.py`）。

⚠ 已知剩余泄漏：记忆层的 `summary_schema.py` / `summary.py` / `long_term.py` 里嵌了预约域的提示词与枚举，需让它们随域可配，属独立改造（白名单记在上述测试里）。

**依赖方向铁律**：单向向下。上层可依赖下层，下层**绝不**反向 import 上层。

## 黄金准则（Golden Principles）

1. **结构化输出 > 字符串解析**：意图/槽位一律用 Pydantic schema + function calling，禁止 `strip().lower()` + 白名单这类脆弱解析。
2. **一个概念一个文件**：尤其工具——`domains/<name>/tools/` 下一个工具一个文件（name/description/args schema/handler）。
3. **工具是薄封装**：tool 内部调用既有 `services/`，**不重写业务逻辑**。
   - 工具超时声明在工具自身（`Tool.timeout`；`None`=取全局缺省 60s，`NO_TIMEOUT`=豁免）。
   - ⚠ 超时**只能中断有 await 点的 handler**。内部跑同步阻塞调用（同步 SQLite / FAISS / 子进程）的工具，声明了 `timeout` 也掐不断——需要真超时就自行 `asyncio.to_thread` 下沉线程池。
4. **显式优于隐式**：消灭"只可意会"的隐藏约定。
5. **会话隔离**：按 `session_id` 隔离状态，禁止全局单例串号。
6. **TAO 循环**：agent 运行时用 Thought→Action→Observation + native tool calling，而非 if/else 路由。

## 不要动（保留资产）

`services/`（业务逻辑）、`db/`（Repository）、`config/model_provider.py`（Provider 抽象）。
重构只换"大脑的决策方式"（`agents/` → `harness/`），**不重写这些**。

例外（已移除，非保留资产）：本地 RAG 的 SQLite+FAISS 知识库实现已于 change `remove-local-rag`
删除，检索改由 `services/knowledge_search.py` 的端口承接，待接入独立的 RAG 项目。

## 验证（每个 change 必须过）

- **测试**：`uv run pytest`（改动相关用例必须绿）。
- **评估集**：`evals/`（Phase 0 建立的 ~20 条用例）——重构前后对照，防回归。
- **原则**：成功静默、只暴露失败；先看测试/评估，不靠"感觉对了"验收。

## Spec 工作流（本项目如何用 OpenSpec）

- 新需求/迭代：`/opsx:propose "描述"` → 生成 `proposal.md`/`design.md`/`tasks.md` → 人审 → `/opsx:apply` → 完成后 `/opsx:archive`。
- **单一真相源**：进行中的变更在 `openspec/changes/<name>/`，完成的归档到 `openspec/changes/archive/`。重构大路线仍以 [harness-refactor-plan.md](../docs/harness-refactor-plan.md) 为准，单个 Phase 落地时再开 OpenSpec change。
- 拿不准先 `/opsx:explore` 想清楚，再 propose。
