## Context

Phase 3 建了 TAO 循环、Phase 5 加了护栏，但可观测性仍停在 Phase 0：`config/logging_setup.py` 提供单行 JSON 日志（root logger + `JsonFormatter`），是"散点日志"而非"trace"——没有 `trace_id` 串联一次请求的多步、没有 span 层级、没有 latency/token 度量。`harness/runtime/agent_loop.py:69-81` 已预留 `on_tool_call`/`on_observation` 钩子但默认 no-op，注释明确写"Phase 6 接入"。评估侧 `evals/run_evals.py` 只产出意图准确率一项，`harness/guardrails/budget.py:40` 已有 `estimate_tokens` 近似可复用。

**约束**（openspec/project.md 黄金准则）：一个概念一个文件；不重写 `services/`、`config/model_provider.py`、RAG；测试离线确定性、不触网；单向依赖向下；按 session_id 隔离。**技术路线已与用户敲定**：自含 tracer 为核心 + 本期真接 OpenTelemetry（测试用 `InMemorySpanExporter`），不引入 LangSmith。

## Goals / Non-Goals

**Goals:**
- 一次请求可回放：`trace_id` 串联 root span（整次 run）与每步 child span，span 含 latency 与 token 近似。
- 记录 `thought / tool_call / observation / latency / tokens` 五类信息。
- `AgentLoop` 接入 tracer，**默认无 tracer 时行为与 Phase 5 完全一致**（向后兼容、可 no-op）。
- 可插 `SpanExporter`：默认 JSON-log exporter；本期实现 OpenTelemetry exporter，测试用 `InMemorySpanExporter` 离线断言。
- 评估多指标报告：意图准确率 + 工具调用正确率 + 槽位抽取完整率 + 端到端延迟。
- 坏 case 落库：`bad_cases` 表 + Repository，最小写入/读取。

**Non-Goals:**
- 不引入 LangSmith 或任何联网 SaaS 上报。
- 不起 Jaeger/Grafana 等可视化后端（OTel 导出可对接，但本期不部署）。
- 不做精确 token 计费（沿用 `estimate_tokens` 字符数/4 近似）。
- 不改既有业务表语义，不重写 services/RAG。
- 不自动把坏 case 写回 `evals/cases.jsonl`（仅落库 + 提供读取，增补由人审）。

## Decisions

### D1：自研 `Tracer` + `SpanExporter` 协议，OTel 作为其中一个 exporter（而非直接全量裸用 OTel API）
- **选择**：内部定义轻量 `Span`（trace_id/span_id/parent_id/name/start/end/attributes/events）与 `Tracer`（`start_span`/`end_span`/`add_event`），输出经 `SpanExporter` 协议（`export(span)`）。提供 `LoggingSpanExporter`（复用 JSON 日志）与 `OTelSpanExporter`（映射到 OpenTelemetry span）。
- **理由**：①守住"核心零联网依赖、离线可断言"——默认 exporter 不需要 OTel 也能跑；②手写 loop 与自研 span 模型契合，避免 OTel async context 传播在手写循环里的易错点（父子关系由我们显式持有，不依赖 OTel 的隐式 context var）；③可插点让"接生产后端"零改业务代码。
- **备选**：直接在 loop 里调 OTel `tracer.start_as_current_span`。否决：强耦合 OTel、async context 传播易断树、测试需更多 OTel 脚手架、默认路径被迫背依赖。

### D2：tracer 经构造参数注入 `AgentLoop`，缺省 `None` 时退化为现有 no-op 钩子
- **选择**：`AgentLoop(..., tracer: Optional[Tracer] = None)`。内部用一个 `_NoopTracer` 或 `None` 守卫；当传入 tracer 时，在循环各点开关 span 并记录 thought（AI 文本）/tool_call/observation/token；`on_tool_call`/`on_observation` 钩子保留（tracer 在其内部或并行调用，两者不互斥）。
- **理由**：向后兼容是硬要求——Phase 0-5 的所有现有测试不得回归。注入式依赖也保持可测（注入 fake tracer 断言事件序列）。
- **备选**：把 tracer 设为必填。否决：破坏现有调用点与测试。

### D3：trace_id 与 session_id 关联但不耦合
- **选择**：`run()` 可接收/生成 `trace_id`；span attributes 里带 `session_id`（若有）。tracer 不读写 session 状态、不参与会话隔离逻辑。
- **理由**：可观测是横切关注点，不应反向依赖会话存储；关联用于检索，耦合会破坏分层。

### D4：评估多指标——分层产出，缺数据的指标显式标注"N/A"而非静默跳过
- **选择**：`run_evals.py` 在现有意图准确率外，对带 `expected_tools`/`expected_slots` 的用例计算工具调用正确率与槽位完整率；端到端延迟由计时得出。用例不含某期望字段时该指标记 N/A 并在报告注明，不伪造分母。
- **理由**：黄金准则"显式优于隐式"——silent skip 会让报告看着覆盖全了其实没有。沿用既有"无 key 优雅降级、成功静默只报错"。
- **备选**：所有用例强制补全期望字段后再算。否决：本期不扩 cases 规模，渐进可用更务实；缺失显式标注即可。

### D5：坏 case 落库遵循 `db/repositories/` 既有 Repository 模式，新增独立表
- **选择**：`db/models.py` 加 `BadCase`（id/trace_id/session_id/user_input/expected/actual/kind[failure|correction]/created_at/extra(JSON)）；`db/repositories/bad_case_repository.py` 提供 `add()` 与 `list_recent()`/`list_by_kind()`。
- **理由**：与 `conversation_repository.py` 等同构，最小侵入；独立表不动旧业务表语义（黄金准则保留资产）。
- **备选**：复用某现有表加字段。否决：污染业务表语义、迁移风险。

### D6：OTel 依赖与初始化隔离，import 失败/未配置时优雅降级
- **选择**：`opentelemetry-sdk` 加入 `pyproject.toml`；`OTelSpanExporter` 内部 lazy import OTel，缺失时给清晰错误（仅当显式启用 OTel exporter 时才需要）。默认 exporter 不 import OTel。
- **理由**：核心路径不被 OTel 拖累；测试默认走 in-memory/fake，不强依赖 OTel 运行时。

## Risks / Trade-offs

- **[token 计数不精确]** → 明确为"近似"（字符数/4，复用 `estimate_tokens`），报告与 span 标注 approximate；精确计费非本期目标。
- **[OTel async context 传播在手写 loop 易断树]** → 用自研 span 显式持有 parent_id，OTel exporter 按我们给的层级重建 span 关系，不依赖 OTel 隐式 context var。
- **[评估多指标依赖 cases 含期望字段，现有用例可能不全]** → 缺字段记 N/A 并报告注明，不伪造分母（D4）；不阻塞本期交付。
- **[新增 OTel 依赖增重 + 潜在版本兼容]** → 仅 `opentelemetry-sdk`，lazy import 隔离；默认路径不触碰。
- **[AgentLoop 接入引入回归]** → tracer 缺省 None 时走原 no-op 路径；新增 tracer 相关测试 + 保证既有 agent_loop 测试全绿（闸门 2 验收）。
- **[坏 case 落库触达真实 DB]** → 测试用既有内存/临时 SQLite 模式（参照 `tests/test_conversation_repository.py`），不触网、确定性。

## Migration Plan

- 纯增量、可回滚：新增 observability 包、新增表/Repository、扩展 evals 与 agent_loop 注入点。
- 不传 tracer 即与现状等价；OTel exporter 不启用即零运行时影响。
- 回滚 = 移除 observability 接入点与新增依赖，旧路径不受影响。

## Open Questions

- RAG 命中率指标是否本期纳入？倾向"尽力而为"：仅当用例含可判定的期望知识命中信号时计算，否则记 N/A（不阻塞交付）。
- 坏 case 增补回 `evals/cases.jsonl` 的人审流程本期不实现，仅留读取接口——确认可接受。
