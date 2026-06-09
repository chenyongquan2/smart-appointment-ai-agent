## Why

当前意图分类与槽位抽取都依赖**脆弱的字符串解析**：`TaskClassifier` 把模型输出 `strip().lower()` 后用白名单兜底（非法即 `other`），`InputParser` 让模型吐裸 JSON 再 `json.loads`、失败就返回兜底 dict。这两处都违反项目黄金准则「结构化输出 > 字符串解析」，是格式错误与误分类的根因（Phase 0 基线唯一错例即源于此），也是后续 native tool calling 的前置障碍。Phase 1 先消灭它们，性价比最高。

## What Changes

- 新增 Pydantic v2 schema：`TaskCategory`（意图枚举 + 可选置信度/理由）、`AppointmentSlots`（覆盖现有全部槽位字段，带枚举/类型约束）。
- `TaskClassifier.classify_task` 内部改用 LangChain `with_structured_output`（function calling）强制模型返回合法枚举，**删除** `strip().lower()` + 白名单兜底；对外签名仍返回 `str`，向后兼容。
- `InputParser` 改用 structured output 约束抽取，**删除** 裸 JSON prompt + `json.loads` + 兜底 dict 的脆弱链路。
- **BREAKING（内部，对 web/ 前端有影响）**：`InputParser.parse_stream` 当前逐 token 流式吐 JSON 给前端。结构化抽取不便逐 token 流式合法 JSON —— 流式 vs 结构化的取舍与兼容策略在 design.md 中决策，确保不破坏现有调用方与测试。

## Capabilities

### New Capabilities
- `intent-classification`: 用户/工作人员消息的意图分类，以受约束的枚举（appointment/query/pay/statistics/other）作为结构化输出，取代字符串解析。
- `slot-extraction`: 预约槽位（性别/时间/时长/项目/偏好/技师/确认等）的结构化抽取，以 Pydantic schema 约束，取代裸 JSON 解析。

### Modified Capabilities
<!-- 无：现有 specs（eval-harness / structured-logging / test-safety-net）的需求不变。 -->

## Impact

- **代码**：`agents/task_classification/task_classifier.py`、`agents/appointment/input_parser.py`（仅这两个文件）。
- **调用方**：`agents/appointment` 内消费 `InputParser` 输出的逻辑、`web/` 前端的流式渲染——需在 design.md 评估兼容影响。
- **保留资产不动**：`services/`、`db/`、`config/model_provider.py`、RAG（SQLite+FAISS）。
- **依赖**：复用既有 Pydantic v2、LangChain 0.3.x（`langchain-openai` 的 `with_structured_output`），不引入新依赖。
- **验证**：`uv run pytest`（现状 21 passed / 9 xfailed 不退化）、`uv run python evals/run_evals.py`（格式错误率→0，端到端不低于基线 95%）。
