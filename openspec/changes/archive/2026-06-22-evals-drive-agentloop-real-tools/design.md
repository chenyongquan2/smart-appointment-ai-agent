## Context

`evals/run_evals.py` 目前只调 `classify_task`，`EvalResult.actual_tools` 恒 `None`，工具调用正确率恒 N/A。生产路径（`api/chat_handler.py`）的主 `AgentLoop` 主 registry **只含 `delegate`**，真实领域工具藏在子 Agent 的工具子集里；而子 Agent 的内层 loop（`harness/subagents/base.py:72`）构造时**未传 tracer**，故其工具调用既不被既有 tracer 看见、也无法被评估采集。

约束：CLAUDE.md 规定改 `harness/` 须走完整 OpenSpec change + 两道闸门；既有 `metrics.py` 纯函数 + `test_eval_metrics.py` 离线确定性单测的姿势必须保留；`temperature=0` 但仍非确定，故真跑分数不可当门禁（§7）。

## Goals / Non-Goals

**Goals:**
- 让评估真跑生产路径（主→`delegate`→子 Agent），采集真实工具调用，使工具调用正确率出真数。
- 修掉「子 Agent 工具调用对 tracer 不可见」的现存盲区。
- 硬门禁只压在离线确定性单测；真跑只作冒烟、不断言百分比。

**Non-Goals:**
- 参数级 / 序列级比对、多委派序列语义（→ 改造 2）。
- 基线持久化 / 阈值阻断 / 接 `/phase` 闸门（→ 改造 6）。
- C-full：子 Agent span 嵌套进主 trace 树（生产尚未挂真 tracer，现做属过度工程）。
- 把真跑接入 `pytest` 默认门禁（真跑要 key、非确定，留作手动冒烟）。

## Decisions

### D1：用 trace 当工具采集源（而非在主 loop 挂 on_tool_call）
- **选**：给子 Agent 内层 loop 透传 tracer，评估从导出的 span 的 `tool_call` 事件读工具序列。
- **弃**：(a) 只在主 loop 挂 `on_tool_call` —— 只看得到 `delegate`，看不到领域工具；(b) 评估侧另起全量工具的扁平 loop —— 评的是生产里不存在的 agent，保真度低。
- **理由**：trace 方案一改两得（顺带修盲区），且评的是真生产路径；`tool_call` 事件已含 `name`+`args`，参数与顺序「免费」拿到，为改造 2 铺路而无需重采。

### D2：C-lite（不嵌套）而非 C-full（嵌套）
- **选**：子 Agent loop 仍各自开 root span，多棵断开的 trace 树。
- **弃**：给 `AgentLoop.run` / `SubAgent.run` 加父 span / trace 上下文传播以嵌套成一棵树。
- **理由**：评估按「每用例一个 exporter 沙盒、收集全部 span」即可，不依赖单一 trace_id；嵌套只为生产 trace UI 美观，而生产路径连真 tracer 都还没挂，先做嵌套属过度工程。

### D3：采集边界 = 每用例一个 InMemoryExporter 沙盒
- **选**：每条用例跑前新建 `Tracer(InMemoryExporter())` + 主 loop，跑完收集该 exporter 内**所有** span 的 `tool_call` 事件，按 `(span.start, 事件顺序)` 排序还原序列。
- **弃**：按主 loop 的单一 `trace_id` 过滤 —— 子 Agent 自开 root 会漏采。
- **理由**：沙盒隔离 + 全量收集，确定性强、用例间互不污染。

### D4：采全比松 —— actual_tools 升为有序 `list[{name, args}]`，指标仍 `set` 名字比较
- **选**：数据模型采全（name+args+顺序），`tool_call_correctness` 维持 `set` 名字比较。
- **弃**：(a) 只采 `list[str]` —— 改造 2 还得回头改采集层；(b) 一步到位做参数/序列比对 —— 连带要给 20 条用例补 `expected_tool_args`，scope 膨胀。
- **理由**：采集与比对解耦——采全、比松，是最稳姿势；改造 2 只改 `metrics.py` + 标注用例，数据已就位。

### D5：分层验收 —— 硬门禁压确定性层
- **选**：硬门禁 = `uv run pytest` 全绿的离线确定性单测（fake `ScriptedChatModel` + `InMemoryExporter`，不触网）；真跑 = 手动冒烟，只看结构不断言分数。
- **弃**：把真跑分数 / 阈值写进门禁。
- **理由**：真跑分来自非确定 LLM，写进门禁即 flaky（违反 §7）；基线+阈值是改造 6 的事。

### D6：tracer 透传的注入路径
- **选**：让 `build_delegate_tool` / `SubAgent.run` 接受并向内层 `AgentLoop` 透传可选 tracer；缺省 `None` → 退化 `NoopTracer`，向后兼容。
- **理由**：与既有「tracer 可选、缺省 Noop」的向后兼容范式一致；评估侧在构造主 loop 时一并注入同一 tracer。

## Risks / Trade-offs

- **真跑慢、要 key、非确定** → 缓解：真跑仅在有 key 时启用，保留无 key 优雅降级；真跑不当门禁，门禁压在 fake-LLM 单测。
- **改 `harness/` 源码（base/delegate）触及生产路径** → 缓解：tracer 缺省 `None` 退化 Noop，保证「未注入时行为完全不变」并加专门单测覆盖该向后兼容场景。
- **`EvalResult.actual_tools` 形状变更**（`list[str]`→`list[{name,args}]`）波及 `test_eval_metrics.py` → 缓解：指标比较语义保持 `set` 名字级，单测随字段形状微调但断言意图不变。
- **多委派工具序列交错语义模糊** → 本次不解决（指标只比名字集合，与顺序无关）；显式留给改造 2 的序列级比对再定义。

## Migration Plan

- 纯增量：评估新增「真跑」路径，原「仅分类器」逻辑可保留为对照或被真跑路径覆盖；`harness/` 改动以「缺省 Noop、行为不变」保证可回滚。
- 回滚：tracer 透传参数缺省 `None`，移除评估真跑路径即回到改造前行为，无数据迁移。

## Open Questions

- 真跑路径是否完全取代原「仅分类器」路径，还是二者并存（分类器准确率仍单独跑）？倾向并存——意图准确率不依赖真跑，保留其轻量、可无 key 看清单的价值。落地时在 tasks 里定。
