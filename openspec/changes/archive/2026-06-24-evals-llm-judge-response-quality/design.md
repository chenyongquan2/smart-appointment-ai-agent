## Context

评估至今全是客观指标，缺「回复质量」这类无唯一答案的主观维度（教材 §6）。改造 4 引入 LLM-as-judge。难点：judge 是 LLM（非确定、触网），不能毁掉改造 1-3 守住的「指标纯函数、可离线确定性单测」根基；且未校准的 judge 不可当真值。judge 需 agent 最终回复作输入，而 `capture_tool_calls` 当前只回工具调用、丢弃回复。

## Goals / Non-Goals

**Goals:**
- 用 LLM-judge 给回复质量出一个 pass/fail 通过率，补最大能力缺口。
- 守住根基：judge 调用层可注入/可 mock，裁决聚合纯函数，结构化裁决。
- 建校准机制（一致率 + Cohen's κ），不造假人工标注；未校准显式标注。

**Non-Goals:**
- pairwise + 位置互换（→ 改造 6，需基线回复作比较对象）。
- RAG 三元组（→ 改造 5，需检索上下文作锚）。
- 换不同裁判模型消自我偏好（单 provider，列局限）。
- 伪造人工标注（绝不）；基线持久化/阈值阻断（→ 改造 6）。

## Decisions

### D1：judge 两层架构——调用层可注入 + 聚合层纯函数（grill Q1）
- **选**：`evals/judge.py` 的 `judge_response(input, reply, llm)` 触网（llm 可注入）；`metrics.response_quality(verdicts)` 纯函数聚合。复刻改造 1「采集层触网 / metrics 纯函数」。
- **弃**：把「调 judge」直接写进指标计算 → 指标变触网、非确定、不可单测。
- **理由**：守根基；fake judge（脚本化 `ScriptedChatModel`）离线确定性测调用层；judge 真实抖动由改造 3 的 `--samples` CI 量化。

### D2：pointwise 现在做，pairwise 留改造 6（grill Q2=C）
- **选**：pointwise 自包含、单次跑即可出质量通过率。
- **弃**：pairwise 现在做——需比较对象；正确锚点是基线回复（改造 6 的持久化），伪造 reference「好回复」对主观质量是可疑锚点。
- **理由**：不为用上 pairwise 就造可疑锚点；judge 接口为 pairwise+位置互换预留。

### D3：二元 pass/fail + 单一复合 rubric + reason 先行（grill Q3）
- **选**：结构化 `{pass: bool, reason: str}`，reason 先于 pass；一次调用一个复合判断（恰当+正确+有帮助揉进 rubric）。
- **弃**：1-5 Likert（绝对分校准差、κ 一致率难算）；拆多维各调一次 judge（成本×N、scope 膨胀）。
- **理由**：二元最稳、最易聚合与校准；reason 先行减少拍脑袋。

### D4：建校准机制、数据留空、不造假（grill Q4）
- **选**：纯函数 `judge_human_agreement` 算一致率 + Cohen's κ；`calibration.jsonl` 占位供人工填；未校准前报告显式标「未校准」。
- **弃**：伪造「人工」标注当真值——毁掉全项目诚实根基。
- **理由**：没挣到的可信度不假装拥有（与全项目 N/A 诚实一致）；机制建好，真值待人补。

### D5：回复采集——surface agent 最终回复
- **选**：扩 `agent_capture` 同时回 `{tool_calls, reply}`；`capture_tool_calls` 保留为薄封装回 `.tool_calls`（改造 1 既有测不破）。
- **理由**：judge 需回复文本作输入，而当前采集丢弃它；向后兼容地补出来。

### D6：`--judge` 默认关
- **选**：judge 为每条额外 LLM 调用，`--judge` 显式开（与 `--samples` 默认关同philosophy）。
- **理由**：不烧钱默认；按需评质量。

## Risks / Trade-offs

- **自我偏好**（judge 与 agent 同模型）→ 列已知局限；理想解换裁判模型，单 provider 暂不可行。
- **长度/宽松偏差** → rubric 明写「按内容不按长度」、temp=0、reason 先行；压不净者写局限。
- **位置偏差** → pointwise 不涉及（单条无 A/B）；连同 pairwise 留改造 6。
- **未校准 judge 被误当真值** → 报告强制「未校准」标注，直到人工填校准集。
- **judge 非确定** → 由改造 3 `--samples` 的 mean±CI 量化（组合而非重复造轮子）。

## Migration Plan

- 纯增量：`--judge` 默认关 → 不开即旧行为。回滚：移除 judge 调用与 response_quality 渲染。无数据迁移（calibration.jsonl 为新增占位）。

## Open Questions

- judge rubric 的具体措辞（pass 的判定标准）需迭代——首版给一个明确但保守的 rubric，后续按校准结果调。落地时定首版文案。
