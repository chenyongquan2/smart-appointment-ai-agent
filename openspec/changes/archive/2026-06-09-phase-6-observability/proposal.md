## Why

harness 跑得动（Phase 3 loop）、跑得稳（Phase 5 护栏），但**看不见、量不准、复不了盘**。当前"trace"只是 Phase 0 留下的散点 JSON 日志（`config/logging_setup.py`），没有 `trace_id` 把一次请求的多步串起来，没有延迟/token 度量；`agent_loop.py` 的 `on_tool_call`/`on_observation` 钩子仍是 no-op；评估只有意图准确率一项指标；失败/纠正的坏 case 用完即弃、无法回流。Phase 6 要补齐"能看见、能度量、能复盘"这一层，让 harness 在重构后可被观测与持续改进。

## What Changes

- **全链路 tracer（新）**：新建 `harness/observability/`，提供一个 `Tracer` 抽象——一次请求 = 一条带 `trace_id` 的 trace，每步 = 一个 span，记录 `thought / tool_call / observation / latency / tokens`。复用 `config/logging_setup.py` 的 JSON 日志作默认 exporter。`AgentLoop` 接上既有 `on_tool_call`/`on_observation` 钩子并补 thought/latency/token 记录；**默认无 tracer 时行为与现状一致（向后兼容、可 no-op）**。
- **可插 exporter + OpenTelemetry 接入（新）**：tracer 输出经 `SpanExporter` 协议抽象；本期实现两个 exporter——默认 JSON-log exporter 与 **OpenTelemetry exporter**（内部 span → OTel span，root/child 层级、`duration`=latency、`attributes`=tokens/工具名/参数）。新增 `opentelemetry-sdk` 依赖。测试用 `InMemorySpanExporter` 离线断言，**绝不触网**。不引入 LangSmith。
- **评估多指标报告（改）**：扩展 `evals/run_evals.py`，在意图准确率之外补 **工具调用正确率、槽位抽取完整率、端到端延迟**（RAG 命中率视用例可得性尽力而为）。自动出报告、成功静默只详列错误、无 API key 时仍优雅降级不崩。
- **坏 case 回流落库（新）**：新增 `bad_cases` 表 + Repository（遵循 `db/repositories/` 既有模式），把失败/用户纠正的 case 落库，供后续补进评估集；提供最小写入与读取接口。**不改动已有业务表语义。**

## Capabilities

### New Capabilities
- `observability`: harness 的可观测层——`trace_id` 串联的 trace/span 模型，记录 thought/tool_call/observation/latency/tokens；可插 `SpanExporter`（默认 JSON 日志 + OpenTelemetry）；`AgentLoop` 经其接入、默认向后兼容。
- `bad-case-feedback`: 失败/纠正 case 的回流落库——`bad_cases` 表与 Repository，最小写入/读取接口，供评估集增补。

### Modified Capabilities
- `agent-loop`: 循环接入 tracer——每步记录 thought/tool_call/observation/latency/token；注入 tracer 为可选依赖，缺省时行为与 Phase 5 一致（无回归）。
- `eval-harness`: 评估运行器从单一意图准确率扩展为多指标报告（工具调用正确率、槽位抽取完整率、端到端延迟），保留无 key 优雅降级与"成功静默只报错"。

## Impact

- **新增代码**：`harness/observability/`（tracer + exporter，一个概念一个文件）；`db/` 新增 `bad_cases` 模型与 `db/repositories/bad_case_repository.py`；`tests/` 新增 tracer/exporter/eval-metrics/bad-case 单测。
- **修改代码**：`harness/runtime/agent_loop.py`（接入 tracer，向后兼容）；`evals/run_evals.py`（多指标）；`pyproject.toml`（加 `opentelemetry-sdk`）；`db/models.py`（新增表，不动旧表）。
- **不碰保留资产**：`services/`、`config/model_provider.py`、RAG（SQLite+FAISS）业务逻辑不重写；既有业务表语义不变。
- **依赖方向**：observability 属 harness 层，向下复用 config 日志；不被 services/db 反向依赖。trace_id 与 session_id 关联但不耦合。
