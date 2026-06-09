## 1. Tracer 核心与 SpanExporter 抽象（observability 能力）

- [x] 1.1 新建 `harness/observability/__init__.py` 与 `harness/observability/span.py`：定义轻量 `Span`（`trace_id`/`span_id`/`parent_id`/`name`/`start`/`end`/`attributes`/`events`）与 latency 计算；时间用可注入 clock（默认 `time.perf_counter`/`time.time`），便于离线确定性测试。
- [x] 1.2 新建 `harness/observability/exporter.py`：定义 `SpanExporter` 协议（`export(span)`）与一个收集型 `InMemoryExporter`（测试用，存全部导出 span）。
- [x] 1.3 新建 `harness/observability/tracer.py`：`Tracer.start_span(name, parent_id=None, attributes=None)` / `end_span` / `add_event(span, kind, payload)`；生成唯一 `trace_id`/`span_id`（可注入 id 工厂，测试确定性）；span 结束时经注入的 exporter 导出。提供便捷记录 `thought`/`tool_call`/`observation`/`tokens`（近似，标注 approximate，复用 `harness/guardrails/budget.estimate_tokens`）。
- [x] 1.4 新建 `harness/observability/logging_exporter.py`：默认 `LoggingSpanExporter`，把 span 序列化为单行 JSON 经既有 logger 输出（复用 `config/logging_setup` 风格）；MUST NOT import OpenTelemetry。
- [x] 1.5 `tests/` 新增 tracer/exporter 单测：root+child 层级与 parent_id、latency 由注入 clock 确定性可断言、token 标注近似、thought/tool_call/observation 事件落到正确 span、InMemoryExporter 可取回断言；全程不触网。

## 2. OpenTelemetry exporter（隔离 + 离线可测）

- [x] 2.1 `pyproject.toml` 增加 `opentelemetry-sdk` 依赖；`uv sync`。
- [x] 2.2 新建 `harness/observability/otel_exporter.py`：`OTelSpanExporter` 把内部 `Span` 映射为 OTel span（root/child 层级一致、`duration`=latency、`attributes`=token 近似/工具名/参数）；OTel 相关 import 在模块内 lazy/隔离，缺失时仅在启用该 exporter 时报清晰错误。
- [x] 2.3 `tests/` 新增 OTel 单测：用 `InMemorySpanExporter` 跑一次 trace，断言 OTel span 的层级、duration、attributes 与内部 span 一致，且不触网；另测"默认 LoggingSpanExporter 路径不 import OTel"。

## 3. AgentLoop 接入 Tracer（向后兼容）

- [x] 3.1 `harness/runtime/agent_loop.py`：构造增加可选 `tracer: Optional[Tracer] = None`（缺省 None → 现有 no-op 路径，行为不变）。
- [x] 3.2 `run()` 接入：整次 run 开 root span（带 `session_id`/`trace_id` attributes），每步开 child span，记录 thought（AI 文本）、tool_call（名+参数）、observation（结果）、该步与端到端 latency、token 近似；保留既有 `on_tool_call`/`on_observation` 钩子语义（两者不互斥）。
- [x] 3.3 `tests/` 新增/补充：注入 tracer 时产生可回放 trace（断言 root+child、工具步含 tool_call/observation/latency）；**未注入 tracer 时既有 agent_loop 测试全绿、行为不变**；tracer 在工具异常/护栏兜底（预算/打转/重试耗尽）下不改变控制流，仅记录 span。

## 4. 评估多指标报告（eval-harness 能力）

- [x] 4.1 `evals/run_evals.py`（或新增 `evals/metrics.py` 报告模块）：在意图准确率外，计算工具调用正确率（用例含 `expected_tools` 时比对，否则 N/A）、槽位抽取完整率（用例含 `expected_slots` 时，否则 N/A）、端到端延迟（每条计时汇总）。
- [x] 4.2 报告输出：多指标总览 + 仅详列判错/异常用例（成功静默）；缺期望字段的指标显式标 N/A 并注明，不伪造分母；保留无 API key 时优雅降级、非零退出、不崩。
- [x] 4.3 `tests/` 新增评估指标单测：用离线 fake 分类/执行注入，断言工具正确率/槽位完整率/延迟的计算与 N/A 标注逻辑，全程不触网（不实际调用真实 provider）。

## 5. 坏 case 回流落库（bad-case-feedback 能力）

- [x] 5.1 `db/models.py` 新增 `BadCase` 表（`id`/`trace_id`/`session_id`/`user_input`/`expected`/`actual`/`kind`/`created_at`/`extra` JSON）；新增独立表，不动既有业务表语义。
- [x] 5.2 新建 `db/repositories/bad_case_repository.py`：`add(...)` 写入；`list_recent(n)` 按时间倒序；`list_by_kind(kind)` 过滤；遵循 `conversation_repository.py` 既有模式。
- [x] 5.3 `tests/` 新增坏 case 单测（参照 `tests/test_conversation_repository.py`）：用临时/内存 SQLite 写读一致、按 kind 过滤、关联 trace_id 持久化；不触网、确定性。

## 6. 验证与归档前自检（闸门 2）

- [x] 6.1 跑 `uv run pytest`：全绿，既有 Phase 0-5 用例无回归，新增 observability/otel/eval/bad-case 用例通过。
- [x] 6.2 跑 `uv run python evals/run_evals.py`（无 key 时验证优雅降级、有 key 时验证多指标报告产出），注入坏输入/异常确认不崩、全程不触网。
- [x] 6.3 核对 Phase 6 验收标准：每次请求可经 trace_id 回放（span 含 latency/tokens）、评估自动出多指标报告、坏 case 能落库——全部达成后方可归档。
