# CLAUDE.md

> Claude Code 的项目常驻指令。保持精简——这是"地图",不是手册。
> 详细约定见 [openspec/project.md](openspec/project.md)；重构路线见 [docs/harness-refactor-plan.md](docs/harness-refactor-plan.md)；概念背景见 [docs/harness-index.md](docs/harness-index.md)。

## 这个项目怎么开发（重要）

本项目用 **plan 驱动的规格驱动开发（OpenSpec SDD）**：

1. **路线图在 [docs/harness-refactor-plan.md](docs/harness-refactor-plan.md)**（Phase 0–7）——它定义"做哪个 Phase、为什么"。
2. **每个 Phase 的落地走一个 OpenSpec change**：`/opsx:propose` → 人审 → `/opsx:apply` → 验证 → `/opsx:archive`。一键触发用 **`/phase <N>`**。
3. **两道闸门不能跳**：
   - **闸门 1（人审）**：propose 生成 `proposal/design/tasks` 后**停下让人审**，批准了才实现。
   - **闸门 2（验证）**：实现后跑 `uv run pytest`（及 `evals/`），**成功静默、只报错**，绿了才归档。
4. **实现任何 Phase 前必须先有一个 active 的 OpenSpec change**；不要直接散改源码。

## 关键约定（详见 [project.md](openspec/project.md)）

- **依赖/运行**：uv（`uv run` / `uv sync`，不要用 pip）。**测试**：`uv run pytest`。
- 结构化输出 > 字符串解析；一个概念一个文件；工具是 `services/` 的薄封装。
- 单向依赖分层；按 `session_id` 隔离状态；TAO 循环而非 if/else 路由。
- **不要重写**：`services/`、`db/`、`config/model_provider.py`。
- **知识库检索**：本地 RAG（SQLite+FAISS）已移除；`search_knowledge` 走 [services/knowledge_search.py](services/knowledge_search.py) 的可替换端口，未接入时明确失败（不返回空列表）。接入独立 RAG 项目 = 实现一个端口 client 并注入。

## 验证

- 改动相关的 `uv run pytest` 必须绿。
- `evals/` 评估集（Phase 0 建立）用于重构前后对照、防回归。
- 成功静默、只暴露失败；不靠"感觉对了"验收。
