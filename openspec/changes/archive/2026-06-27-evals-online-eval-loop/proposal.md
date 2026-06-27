## Why

评估体系（改造 1–6）目前只有「离线」一条腿：用例集是手写合成的，门禁守的也只是这批静态用例。`agent-eval-fieldguide.md` §13 的「在线」那条腿（trace 采样 → 标注 → 回灌）一直缺失——而**生产入口 [api/chat_handler.py:53](../../../api/chat_handler.py) 的 `AgentLoop` 根本没接 `tracer=`**，生产路径不产出、也不持久化任何 trace，所以「采样生产 trace」当前**无 trace 可采**。

本变更（改造 7）补上在线闭环：让真实对话留下可检索的 trace → 半自动甄别坏 case → 人审标注后回灌进 `evals/cases.jsonl`，形成「线上发现问题 → 离线防住它」的回路。依赖改造 6（已落地的回归门禁）——有了门禁，回灌才有意义。

## What Changes

- **新增持久化文件 SpanExporter**：`FileSpanExporter`（复用 `Span.to_dict()`），把结束的 span 以单行 JSON 追加落盘到 `evals/traces/*.jsonl`。`export()` 内吞异常、失败仅 warning（沿用既有「exporter 不得抛」契约）。
- **接进生产**：给 [chat_handler.py](../../../api/chat_handler.py) 的 `AgentLoop` 注入 tracer + 文件 exporter，使真实对话产出 trace。采样口径：**全量落盘 + 错误优先**（命中 `max_steps` / 工具异常 / `[ERROR]` / 兜底回复 必留），留 `sample_rate` 旋钮默认 `1.0`。
- **新增半自动 triage CLI**（`evals/triage.py`）：从持久化 trace 读入，用已有信号（max_steps / 工具错 / 兜底 / `[ERROR]`）给 trace 打「疑似坏」标，**人工最终确认 + 标注真值**（真值绝不自动伪造）。
- **回灌 `cases.jsonl`**：人审通过的候选追加进 `evals/cases.jsonl`，按 `input` 规范化**去重**，加 `"source":"online"` 溯源 + `// --- online 回灌 ---` 分节。回灌后**不自动 re-baseline**，CLI 末尾打印提醒「用例集已变，需 `--update-baseline`」（基线变更走人审，不绕过改造 6）。
- **存储与忽略**：trace 落 `evals/traces/`（运行期产物，加进 `.gitignore`，与 `data/`、`logs/` 一致）。
- **文档**：`evals/README.md` 记在线闭环用法 + 诚实边界（本项目无真实用户，「生产 trace」=开发/手动对话或回放输入，非真实流量）；`docs/agent-eval-fieldguide.md` §13 改造 7 状态从「当前待做」改为已落地。

## Capabilities

### New Capabilities
<!-- 无新增能力；复用既有 observability 与 bad-case-feedback 两个能力 -->

### Modified Capabilities
- `observability`: 新增「持久化文件 SpanExporter 与生产接线（采样）」要求——在既有可插 `SpanExporter` 抽象之上提供一个落盘 exporter，并把 tracer 接进生产 `AgentLoop`，按「全量 + 错误优先」采样产出可检索 trace。
- `bad-case-feedback`: 新增「从持久化 trace 半自动甄别坏 case」与「人审标注并回灌 `evals/cases.jsonl`」两条要求。既有 spec 明确把「增补评估集」留给人审、本能力只负责 DB 落库/读取；本变更补上人审闸门下的 trace→甄别→标注→回灌闭环（去重、溯源、提醒重定基线），不改动既有 `bad_cases` DB 表语义。

## Impact

- **改动代码**：新增 `harness/observability/file_exporter.py`、`evals/triage.py`；修改 `api/chat_handler.py`（接 tracer/exporter）、`.gitignore`、`evals/README.md`、`docs/agent-eval-fieldguide.md`。
- **可复用资产**：`evals/trace_collect.py`（`collect_tool_calls` 从 span 还原有序工具序列）、`evals/agent_capture.py`（per-case exporter 沙盒 + tracer 透传子 Agent）、`harness/observability/exporter.py`（`SpanExporter` Protocol）、`harness/observability/span.py`（`Span.to_dict()`）。
- **不破坏**：默认路径仍不依赖 OpenTelemetry；`run_evals.py` 的 `load_cases` 已验证容忍额外字段（`source` 不影响运行器）；改造 6 门禁不受影响（回灌→重定基线仍走人审）。
- **生产开销**：tracer 落盘为同步追加写，量小（学习项目）；`export()` 吞异常保证不拖垮主流程。
- **测试**：trace 还原 / 甄别 / 去重回灌均做成纯函数 + 离线确定性单测（仿改造 6 `compare_to_baseline`），无 key 也能跑、可进闸门 2。
