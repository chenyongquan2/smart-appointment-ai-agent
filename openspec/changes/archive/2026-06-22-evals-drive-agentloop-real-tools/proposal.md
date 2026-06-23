## Why

当前 `evals/run_evals.py` 只驱动意图分类器 `classify_task`，`actual_tools` / `actual_slots` 恒为 `None`，导致 `metrics.py` 的工具调用正确率、槽位完整率实跑恒为 N/A——项目实质只评到「组件级-意图分类」，而非「agent 评估」。`eval-harness` 现有要求已写明「应在 `expected_tools` 存在时计算工具调用正确率」，但实现从未驱动 loop，该要求长期落空。

同时存在一个现存可观测性盲区：子 Agent 的工具调用对 `Tracer` 完全不可见——`harness/subagents/base.py` 构造子 Agent 内层 `AgentLoop` 时未传 tracer，真实领域工具（`find_technician` 等）跑在子 Agent loop 里却不被导出。修掉它，评估就能直接复用 trace 作为工具调用的数据源（一改两得）。

## What Changes

- **修可观测盲区**：把 tracer 透传进子 Agent 的内层 `AgentLoop`，使子 Agent 的 `tool_call` / `observation` 被正常导出。子 Agent 仍各自开 root span（多棵 trace 树，可接受）；不做父 span 嵌套传播（C-full 留作后续）。
- **评估真跑端到端**：`run_evals.py` 新增「真跑 AgentLoop」路径——用 `build_default_registry()` + `build_default_subagent_registry()` + `build_delegate_tool()` 拼一个带真 `Tracer(InMemoryExporter())` 的主 loop（不复用 `chat_handler` 的 NoopTracer 单例），逐条用例在独立 exporter 沙盒里跑，收集该 exporter 内所有 span 的 `tool_call` 事件，按 `(span.start, event 顺序)` 还原有序工具序列。
- **采全比松**：`EvalResult.actual_tools` 从 `list[str]` 升为有序 `list[{name, args}]`（args 与顺序一并采下），但工具调用正确率指标仍只做 `set` 名字比较（语义不变，不破坏既有单测）。**BREAKING**（数据模型字段形状变更，影响 `metrics.py` 内部与其单测）。
- **分层验收**：硬门禁压在离线确定性单测（fake LLM + InMemoryExporter，不触网、不要 key）；真跑只作冒烟，不断言具体百分比。

## Capabilities

### New Capabilities
<!-- 无新增能力；本变更修改两个既有能力 -->

### Modified Capabilities
- `eval-harness`: 新增「评估运行器真跑端到端 `AgentLoop` 并从 trace 采集真实工具调用序列」的要求，使工具调用正确率从恒 N/A 翻成真实数字；明确「采全（name+args+顺序）、比松（仅名字集合）」，参数级/序列级比对显式不在本次范围。
- `observability`: 新增「`Tracer` 必须能透传进子 Agent 的内层 `AgentLoop`」的要求，消除子 Agent 工具调用不可见的盲区。

## Impact

- **源码**：`harness/subagents/base.py`、`harness/subagents/delegate.py`（tracer 透传）；`evals/run_evals.py`（真跑路径）；`evals/metrics.py`（`EvalResult.actual_tools` 形状）。
- **测试**：新增「span→有序工具序列」抽取测、「fake LLM 驱动链路填 actual_tools」测；`tests/test_eval_metrics.py` 需随数据模型微调但保持 `set` 比较语义。
- **运行**：真跑 loop 多次调 LLM → 评估变慢、要 key；保留无 key 优雅降级，真跑仅在有 key 时走。
- **显式不在范围**：参数级/序列级比对 + 多委派序列语义（→ 改造 2）；基线持久化 + 阈值阻断 + 接 `/phase` 闸门（→ 改造 6）；C-full 子 Agent span 嵌套进主 trace 树（生产路径尚未挂真 tracer，现做属过度工程）。
