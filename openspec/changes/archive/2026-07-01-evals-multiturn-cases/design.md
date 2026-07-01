## Context

改造 1（archive `evals-drive-agentloop-real-tools`）已让运行器真跑 `AgentLoop` 并采集 `actual_tools`/`actual_slots`，但**只跑单轮**：

- `evals/run_evals.py:_run_once` 对每条用例取 `case["input"]`（单字符串），调 `classify_task(text)` 与 `run_and_capture(text, ...)`。
- `evals/agent_capture.py:run_and_capture(user_input: str, ...)` 构造一个带 `Tracer`/`InMemoryExporter` 沙盒的主 loop，`async for token in loop.run(user_input)` 跑一次，从 `exporter.spans` 还原工具序列与末条 `[REPLY]`。
- `cases.jsonl` 29 条全为单轮。

而 `AgentLoop.run(user_input, history: Optional[list[BaseMessage]] = None)`（[agent_loop.py:98](../../../harness/runtime/agent_loop.py#L98)）**已支持传入历史**——每次 run 从 `[System] + history + [Human(user_input)]` 重建消息。生产 `chat_handler` 正是按「最近 N 轮 user/assistant 对」喂 `history`。这意味着多轮评估**不需要改 harness**，只需在评估层加一个「按轮驱动 + 累积 history」的外层循环。

约束（来自 [CLAUDE.md](../../../CLAUDE.md) 与项目记忆）：① 禁改 `services/`、`harness/runtime`、子 Agent 编排与系统提示；② 改 `cases.jsonl` 必重定 baseline；③ 单条工具触发强非确定，稳定性靠数据集冗余而非改写单条。

## Goals / Non-Goals

**Goals:**

- 让 `cases.jsonl` 支持多轮 `turns` 用例形态，向后兼容既有单轮 `input`。
- 运行器对多轮用例按轮驱动同一 loop、累积 history、**跨所有轮次**还原工具序列与槽位。
- 复用单轮已有的沙盒构造与 `collect_tool_calls` 还原逻辑，不复制采集实现。
- 新增多轮采集的离线确定性单测（脚本化 fake LLM）。
- 补几条「追问补全 / 改约 / 先咨询后预约」式多轮用例，真正落到「轨迹/多轮」评估层。

**Non-Goals:**

- 不改 `metrics.py` 的指标算法与口径（工具 F1、槽位完整率、judge 等照旧吃 `actual_tools`/`actual_slots`/`reply`）。
- 不重构单轮意图分类器去「多轮意图融合」——多轮意图对首轮判定即可。
- 不引入跨 loop 的 correlation id（子 Agent 自开 root 的关联仍按改造 7 的「跨 loop 关联待后续」边界）。
- 不追求多轮用例「绝对稳定触发」——沿用数据集冗余 + 容差 + `--samples` 的既有稳定化手段。

## Decisions

### D1 · 用例形态：`turns` 列表与 `input` 二选一，单轮等价单元素 turns

`cases.jsonl` 用例新增可选 `turns: list[str]`。加载时（`load_cases`）：一条用例 MUST 恰好提供 `input` 或 `turns` 之一，否则报行号并 `SystemExit(2)`（与既有「坏用例不静默」一致）。内部统一归一为 `turns`：单轮 `input` → `[input]`。`expected_intent` 校验不变。

**为何不复用 `input` 塞列表**：`input` 既有语义是字符串，塞列表会破坏向后兼容与可读性；显式 `turns` 键让单/多轮在文件里一眼可辨。

### D2 · 按轮驱动：复用同一沙盒 loop，累积 history

`agent_capture.py` 新增 `run_and_capture_multiturn(turns: list[str], llm, full_registry, subagents) -> CaptureResult`：

```
exporter = InMemoryExporter(); tracer = Tracer(exporter)
delegate = build_delegate_tool(llm, full_registry, subagents, tracer=tracer)
main_registry = ToolRegistry(); main_registry.register(delegate)
loop = AgentLoop(llm, main_registry, build_system_prompt(...), tracer=tracer)

history: list[BaseMessage] = []
reply = ""
for turn in turns:
    reply = ""
    async for token in loop.run(turn, history=list(history)):
        if token.startswith(_REPLY_PREFIX): reply = token[len(_REPLY_PREFIX):]
    history.append(HumanMessage(content=turn))
    history.append(AIMessage(content=reply))   # 末轮回复即喂 judge 的 reply
return CaptureResult(tool_calls=collect_tool_calls(exporter.spans), reply=reply)
```

关键点：
- **同一 exporter 跨所有轮次** → `collect_tool_calls(exporter.spans)` 自然按 `(span.start, 事件序)` 跨轮还原有序工具序列。无需按 trace_id 过滤（子 Agent 自开 root，沿用单轮既有处理）。
- **history 只含 user/assistant 对**，不回灌中间工具消息——与生产 `chat_handler` 的窗口口径一致（每轮 `loop.run` 自己重建 `[System]+history+[Human]`，轮内工具消息是该 run 的内部状态）。
- 既有 `run_and_capture(user_input)` 保留不动；可将其实现改写为 `run_and_capture_multiturn([user_input])` 的薄封装以避免两份沙盒代码（**优先**，DRY），但 MUST 保持其签名与返回不变（改造 1 的调用点/单测依赖它）。

**备选（否决）**：让 `_run_once` 直接内联多轮循环——会把沙盒构造泄漏进运行器、难单测；放 `agent_capture` 与单轮对称、可注入 fake LLM 测。

### D3 · 运行器分派：`_run_once` 按 `turns` 长度选路径

`_run_once` 里把 `text = case.get("input")` 改为统一取归一后的 `turns`：
- 意图分类对 `turns[0]` 跑 `classify_task`（多轮意图对首轮判定，D 见 proposal）。
- 采集：`turns` 长度为 1 走 `run_and_capture`（保持单轮路径字节级不变），>1 走 `run_and_capture_multiturn`。
- 其余（`expected_tools`/`expected_slots`/`expected_tool_args` 比对、judge、延迟）口径不变——它们只吃 `CaptureResult` 与 case 字段。

延迟仍只计**首轮分类器单次调用**（与既有口径一致、不扩为全链路；§5.6 教材已注明这是已知局限，本切片不改口径以免基线不可比）。

### D4 · 多轮用例选题：覆盖单轮盲区的三类轨迹

新增多轮预约用例（标 `expected_tools`/`expected_slots`，口径=整段累计）：
- **追问补全**：首轮信息不全（如「我想约个按摩」）→ 子 Agent 追问 → 次轮补全时间/技师 → 触发工具链。直击「跨轮补槽位」。
- **改约**：先约定一个时间，再「改到明天同一时间」。
- **先咨询后预约**：首轮 `query`（问项目/价格）→ 次轮转预约。注意：此类**首轮意图是 query**，若标 `expected_intent=query` 则意图口径自洽；若想标 appointment 需让首轮即预约——选题时明确每条的首轮意图，避免 D3 的首轮判定与 `expected_intent` 打架。

数量上沿用改造 8「数据集冗余」思路：多轮触发同样非确定，故每类备几条，靠 `--samples` + 容差吸收。具体条数与措辞在 apply 阶段据实测触发率定（先补 4–6 条，跑 `--samples 3` 看槽位/工具是否稳定非 N/A）。

### D5 · 重定基线（人审闸门）

新增多轮用例改变评估集，`expected_tools` 累计口径也可能改变工具 F1 的分布。apply 完成、`pytest` 绿后，经**人审批准**在新集上 `--update-baseline --samples 3` 重定 `baseline.json`；非自动、不在 `--gate` 路径里偷改（沿用改造 6/8 的基线变更走人审约定）。

## Risks / Trade-offs

- **[多轮触发更不稳定]** 轮次越多，「某轮没按预期触发工具」的累积概率越高 → 槽位/工具指标更容易 N/A。**Mitigation**：D4 每类备多条做冗余；首轮信息尽量齐全的「追问补全」用例把不确定性集中在一处；`--samples 3` 守均值；容差 0.20 吸收抖动。极端非确定下单跑仍可能回落，报告如实标注（沿用改造 8 诚实边界）。
- **[history 口径与生产不完全一致]** 评估里 `reply` 取 `[REPLY]` 末条作为 assistant 轮内容，而生产 `chat_handler` 的窗口可能含更丰富的回合记录。**Mitigation**：二者都只保留 user/assistant 文本对、不含工具消息，对「模型下一轮能看到什么」的近似足够；差异在文档/README 注明为已知简化。
- **[首轮意图 vs 整体意图]** 「先咨询后预约」用例首轮是 query、整体目标是 appointment，首轮判定会把它算作 query。**Mitigation**：D4 选题时让 `expected_intent` 跟随首轮，不制造口径冲突；这本身也是诚实的口径（开场意图）。
- **[基线不可比]** 不重定基线会让旧基线（29 条单轮）与新集 apples-to-oranges 误报。**Mitigation**：D5 人审重定，like-to-like。

## Migration Plan

1. 改 `load_cases` 支持 `turns`/`input` 互斥校验与归一。
2. `agent_capture` 加 `run_and_capture_multiturn`，并（优先）把 `run_and_capture` 改为其单元素薄封装。
3. `_run_once` 按归一 `turns` 分派；单轮路径保持不变。
4. 加离线确定性单测（fake LLM 脚本化逐轮工具调用）。
5. 补 4–6 条多轮用例，`uv run python evals/run_evals.py --limit ... --samples 3` 实测触发率，据实增删。
6. `uv run pytest` 绿 → 人审批准 → `--update-baseline --samples 3` 重定基线 → `--gate --samples 3` 多次确认稳定守 3 项。
7. 更新 `docs/agent-eval-fieldguide.md`（§2/§13）与 `evals/README.md`。

回滚：纯 `evals/` + 文档变更，`git revert` 该 change 的提交并恢复旧 `baseline.json` 即可，不触业务逻辑。

## Open Questions

- 多轮用例的**条数**与**首轮信息齐全度**取多少能让槽位/工具稳定非 N/A——留到 apply 阶段据实测触发率定（D4）。
- 是否给多轮用例引入 `expected_intent_per_turn`（逐轮意图）——本切片**不做**，保持首轮判定；若将来要评「轮内意图漂移」再单开 change。
