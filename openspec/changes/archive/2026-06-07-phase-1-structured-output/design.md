## Context

Phase 1（见 `docs/harness-refactor-plan.md`）要消灭两处字符串解析：

- `agents/task_classification/task_classifier.py`：`classify_task` 用 `content.strip().lower()` + 白名单 `valid_categories` 兜底，非法或异常都归 `other`。
- `agents/appointment/input_parser.py`：`parse_stream` 让模型吐裸 JSON 并逐 token `yield`，`parse_data` 用 `json.loads` 解析、失败返回兜底 dict。

约束（`openspec/project.md` 黄金准则）：结构化输出 > 字符串解析；只改 agents 层这两个文件；不动 `services/`/`db/`/`config/model_provider.py`/RAG；技术栈 Pydantic v2 + LangChain 0.3.x（`langchain-openai`）。

**关键现状（影响"流式 vs 结构化"决策）**：`agents/appointment_agent.py:94-97` 的调用方注释明确写道"内部 JSON，不向用户流式输出，避免英文字段名暴露在聊天界面"，并把 `parse_stream` 的所有 token 累积进 `ai_content` 后才 `parse_data`。即：当前流式**仅是名义上的**，token 被完整缓冲后整体解析，对用户没有任何逐字渲染价值。

## Goals / Non-Goals

**Goals:**
- 用 Pydantic v2 schema + LangChain `with_structured_output` 替换两处字符串解析。
- 保持 `TaskClassifier.classify_task` 返回 `str`、`InputParser` 产出与现有调用方/测试兼容的数据视图，向后兼容。
- 评估集格式错误率→0；端到端不低于 Phase 0 基线（意图 95%）。

**Non-Goals:**
- 不引入 native tool calling 的 agent loop（Phase 3）。
- 不改 web/ 前端真正的"逐字流式"体验（当前抽取步骤本就不逐字渲染）。
- 不重写槽位判断业务逻辑（`info_complete`/`missing_info` 的语义沿用，仅换抽取方式）。

## Decisions

### 决策 1：用 `llm.with_structured_output(Schema)` 而非手解析
- **选择**：为两处分别定义 `TaskCategory`（含 `category: Literal[...枚举]`，可选 `confidence`/`reason`）与 `AppointmentSlots`（覆盖全部 10 个字段），用 `llm.with_structured_output(Schema)` 构建 chain。
- **理由**：function calling 在协议层强制合法结构，删掉 `strip().lower()`/白名单/`json.loads`/兜底 dict。LangChain 0.3.x + langchain-openai 原生支持，无新依赖。
- **备选**：(a) PydanticOutputParser（仍是文本解析，不如 function calling 可靠）；(b) 手写 JSON repair（脆弱）。均不采用。

### 决策 2：classify_task 内部结构化、对外仍返回 str
- **选择**：`classify_task` 内部 `await chain.ainvoke(...)` 得到 `TaskCategory`，返回 `result.category`（str）。
- **理由**：调用方（`task_classification` 处理链）只消费 str 类别，签名不变即零改动、零回归。

### 决策 3：InputParser 去流式，改非流式结构化抽取 + 保留兼容数据视图
- **选择**：新增 `async def extract(user_input, chat_history) -> AppointmentSlots`，内部走 `with_structured_output`。保留 `parse_data` 返回 `dict` 视图（由 `AppointmentSlots.model_dump()` 得到）以兼容 `appointment_agent` 和测试中 `data.get(...)` 的用法。`parse_stream` 的逐 token 流式予以移除/改造——因为调用方本就把它缓冲后整体解析，无 UX 回归。
- **兼容策略**：
  - `appointment_agent.run_stream` 第 1 步由"累积 parse_stream + parse_data"改为"`slots = await extract(...)`；`data = slots.model_dump()`"，下游 `data.get("unrelated")` 等保持可用。
  - 现有 `chat_history` 写入（Human/AI 消息）行为保留。
  - 测试 `test_appointment_agent.py` 中以 `for token in parse_stream(...)` 取 `ai_content` 的两处，需同步改为调用 `extract`/`parse_data` 的新形态（属本 change 的测试更新，不算破坏第三方）。
- **备选**：保留 parse_stream 仅为流式占位（流式抽取 partial JSON）——复杂且无收益，不采用。

### 决策 4：异常降级语义保留、但触发点从"解析失败"前移到"LLM 调用失败"
- **选择**：结构化输出让"解析失败"不再发生；仅当 LLM 调用本身异常时，分类降级 `other`、抽取返回 `info_complete=false` 的默认 `AppointmentSlots`，并记录结构化日志（对齐已落地的 structured-logging）。

## Risks / Trade-offs

- **[模型/Provider 对 function calling 的支持差异]** → 依赖 `langchain-openai` 的 `with_structured_output`，本项目 Provider 抽象已基于 OpenAI 兼容接口；若某 Provider 不支持，fallback 走 `method="json_mode"`，仍以 Pydantic 校验把关。
- **[结构化输出可能比纯文本稍慢/略增 token]** → Phase 1 不做性能优化，延迟监控留待 Phase 6；可接受。
- **[去流式改动触及 appointment_agent 调用点]** → 改动极小且调用方本就缓冲；用现有 pytest（21 passed / 9 xfailed）守护，确保不退化。
- **[start_time 相对时间换算依赖 prompt 语义]** → 将换算规则放进 schema 字段 description，保留现有 `time_config` 注入的当前时间，行为不变。

## Migration Plan

1. 新增 schema（`TaskCategory`、`AppointmentSlots`）—— 与现有字段一一对应。
2. 改 `TaskClassifier` 内部走结构化，签名不变。
3. 改 `InputParser`：加 `extract`，`parse_data` 改为基于 schema 的视图，移除/改造 `parse_stream`。
4. 调整 `appointment_agent.run_stream` 第 1 步调用点。
5. 跑 `uv run pytest` + `uv run python evals/run_evals.py` 对照基线。
6. **回滚**：本 change 仅触两文件 + 一处调用点，`git revert` 即可恢复。

## Open Questions

- 无阻塞性问题。`confidence`/`reason` 字段为可选增强，若实现期发现影响兼容可只保留 `category`/槽位字段（不影响验收）。
