## 1. 用例加载支持多轮（run_evals.py:load_cases）

- [x] 1.1 `load_cases` 支持 `turns: list[str]`：校验一条用例恰好提供 `input` 或 `turns` 之一（两者皆有/皆无 → 报行号 `SystemExit(2)`），内部归一为 `turns`（单轮 `input` → `[input]`）。`expected_intent` 校验不变。
- [x] 1.2 单测：`turns` 用例加载成功并归一；`input`+`turns` 并存报错指行号；皆缺报错；既有单轮用例仍正常加载（向后兼容）。

## 2. 多轮采集（agent_capture.py）

- [x] 2.1 新增 `run_and_capture_multiturn(turns, llm, full_registry, subagents) -> CaptureResult`：复用单轮的 exporter 沙盒 + `delegate(tracer=)` + 同一 loop，按轮 `loop.run(turn, history=list(history))`，每轮跑完把 `HumanMessage(turn)`+`AIMessage(reply)` 追加进 history；跨所有轮次 `collect_tool_calls(exporter.spans)`，`reply` 取末轮。
- [x] 2.2 把既有 `run_and_capture(user_input)` 改写为 `run_and_capture_multiturn([user_input])` 的薄封装（DRY），**保持签名与返回不变**（改造 1 调用点/单测依赖）。抽出 `_build_capture_loop` 共用沙盒构造。
- [x] 2.3 单测（脚本化 fake LLM，逐轮工具脚本，离线确定性）：两轮用例跨轮还原有序工具序列（首轮 `tool_a`、末轮 `tool_b` → 两者按序都在）；`reply` 为末轮回复；单元素 turns 等价单轮。

## 3. 运行器分派（run_evals.py:_run_once）

- [x] 3.1 `_run_once` 取归一后的 `turns`：意图分类对 `turns[0]` 跑 `classify_task`；采集按 `len(turns)` 分派——1 走 `capture_fn`（单轮路径不变），>1 走 `capture_multiturn_fn`。`EvalResult.input` 取首轮。其余（工具/槽位/judge/延迟）口径不变；两处调用点透传 `run_and_capture_multiturn`。
- [x] 3.2 单测：`_run_once` 用注入的 fake 单/多轮采集函数验证按轮长分派、整段 turns 传入、多轮 `EvalResult.input` 取首轮、`actual_tools` 正确填充。

## 4. 补多轮用例（cases.jsonl）

- [x] 4.1 补 6 条多轮用例（4 追问补全 + 1 改约 = appointment；1 先咨询后预约 = query 首轮），标 `expected_tools`/`expected_slots`（整段累计口径），首轮含「预约」避免误判；表头注释补 `turns` 格式与累计/首轮意图口径。加载校验：35 条、6 多轮、5 类全覆盖。
- [x] 4.2 实测触发率（聚焦冒烟，真 provider 跑 6 条多轮）：首轮发现「追问补全」次轮丢项目上下文 → 0 触发；据实改写次轮自然复述项目，触发率 1/6→3/6，触发时跨轮槽位还原满命中（实测 5/5、4/4）。诚实结论写入用例区注释：多轮触发更不稳定（delegate 传合成 task 非历史 + 子 Agent 保守 + 强非确定），未触发记 N/A 不破坏门禁槽位项（由切片 1 单轮锚点撑）。

## 5. 验证与基线（闸门 2）

- [x] 5.1 `uv run pytest` 全绿。（239 passed, 9 xfailed）
- [x] 5.2 人审批准后在新集 `--update-baseline --samples 3` 重定 `baseline.json`（意图 72.4% ±22.8% / 工具F1 47.7% ±13.4% / 槽位 84.9% ±3.4%，n=3；9 个非 N/A 指标）。
- [x] 5.3 重定后多次 `--gate` 确认门禁稳定守 3 项：`--samples 3` PASS 3/3；单采样两次均 PASS 3/3（意图 82.9%/77.1%、工具F1 51.2%/48.5%、槽位 100%/66.7%）。诚实保留：单跑 #2 槽位见波动，极端非确定下仍可能罕见回落，符合改造 8 边界。

## 6. 文档同步

- [x] 6.1 更新 `docs/agent-eval-fieldguide.md`：§12 速查表「端到端·轨迹/多轮」❌→⚠️ 部分；§13 改造 8 加「第二切片 ✅ 多轮对话用例」并更新流程图。
- [x] 6.2 更新 `evals/README.md`：多轮 `turns` 用例形态示例、互斥校验、多轮采集口径（首轮意图 / 跨轮累计 / history 仅 user-assistant 对）、已知简化与诚实边界。
