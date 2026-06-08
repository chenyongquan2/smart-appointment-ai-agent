## Context

Phase 0–4 已落地：结构化输出、工具层、TAO 循环、会话隔离与分层记忆。当前 `AgentLoop`（`harness/runtime/agent_loop.py`）裸调用 `await self.llm.ainvoke(messages)`，无超时/重试；危险写操作 `create_appointment` 与只读查询走同一条 `ToolRegistry.dispatch`，无权限区分；循环唯一护栏是构造期固定的 `max_steps=8`。`config/model_provider.py` 是保留资产（不改），且不同 provider 的 LLM 实例统一为 LangChain `BaseChatModel`，故护栏应在 harness 层、围绕 `ainvoke` 这个调用点做包裹，而非进入 provider。

约束（黄金准则）：一个概念一个文件；结构化输出优先；工具是薄封装；不重写 `services/`/`db/`/`model_provider`/RAG。Phase 5 验收：注入坏输入/超时/工具异常时 harness 不崩、优雅降级，`pytest` 与 `evals` 绿。

## Goals / Non-Goals

**Goals:**
- LLM 调用具备超时 + 指数退避重试，耗尽后优雅降级（不抛栈到 Channel 层）。
- 危险工具操作（`create_appointment`）经一道可注入的权限闸门，可被策略拒绝并把结构化拒绝结果回灌给模型。
- 循环在 `max_steps` 外，增加累计 token 预算上限与"连续相同工具调用"打转检测。
- 既有"工具失败回灌不崩 loop"有显式回归测试。
- 全部护栏离线可测（fake LLM / fake 异常注入，不触网）。

**Non-Goals:**
- 不做分布式限流 / 令牌桶限流（单进程内 best-effort，留待 Phase 6 观测后再定）。
- 不接入真实计费 token 计数器；预算用消息体量的近似估算即可（详见 Decisions）。
- 不实现交互式人工确认 UI；权限闸门以可注入策略对象表达，默认放行。
- 不改 `model_provider.py`、`services/`、`db/`、RAG。

## Decisions

### D1. 护栏放在 harness 层、包裹 `ainvoke`，而非改 provider
`model_provider.py` 是保留资产，且 LangChain 已有内建 retry，但其行为不可控、且不覆盖"超时后优雅降级"。决定在 `harness/guardrails/` 新建薄封装，`AgentLoop` 调用 `guarded_invoke(self.llm, messages)` 取代裸 `ainvoke`。
- **备选**：用 `llm.with_retry()`（LangChain 内建）。否决：无法统一超时语义，也难做确定性单测（要触网或精细 mock 内部）。

### D2. 超时 + 指数退避重试合为一个 `harness/guardrails/retry.py`（含 timeout）
`retry.py` 暴露一个 async helper：对传入的 async 调用施加 `asyncio.wait_for` 超时，按 `max_attempts` + 指数退避（base * 2^n）重试可重试异常（超时、连接类）。退避用可注入 sleep（测试传 no-op，避免真睡）。耗尽后抛一个明确的 `GuardrailExhausted` 异常，由 `AgentLoop` 捕获转兜底回复。
- 一个概念一个文件：超时是重试的一个触发条件，逻辑紧耦合，合在 `retry.py` 内（timeout 作为其参数），不强行拆成两文件造成跨文件状态。
- **备选**：拆 `timeout.py` + `retry.py` 两文件。否决：超时只是 `wait_for` 一行，单独成文件反而割裂；如评审更看重映射 plan 的"超时/重试"两词，可在 apply 时拆——记为 Open Question。

### D3. token 预算用"近似估算"而非真实计费
无统一跨 provider 的 token 计数 API（保留资产不改）。`harness/guardrails/budget.py` 用消息字符数 / 4 的粗略估算累计每步 prompt+completion，超过 `max_tokens` 预算即终止循环转兜底。预算是"防失控的上限"，近似足够；精确计量留待 Phase 6 观测。
- **备选**：用 `tiktoken` 精确计数。否决：引入新依赖、且非 OpenAI 模型不准；过度工程。

### D4. 打转检测：连续 N 次相同 (name, args) 工具调用即判定
`budget.py`（或 loop 内）记录上一步工具调用签名，若连续 `repeat_limit`（默认 3）次出现完全相同的 `(name, sorted(args))`，判定打转，终止转兜底。这是 `max_steps` 之外更早的逃生口。

### D5. 权限闸门：`Tool.dangerous` 标记 + `ToolRegistry` 注入式策略
`Tool` dataclass 加 `dangerous: bool = False` 字段（向后兼容，默认 False）。`create_appointment` 标 `dangerous=True`。`ToolRegistry` 新增可选 `permission` 策略（一个 callable：`(tool, args) -> Decision`，Decision 为 allow/deny+reason 的结构化对象）。`dispatch` 对危险工具先问策略；deny 时**不执行 handler**，返回结构化拒绝结果（经既有 `_dispatch` 回灌路径喂回模型）。默认策略放行（保持现有行为，不破坏既有测试）。
- **备选**：在 `AgentLoop` 里硬编码"create_appointment 需确认"。否决：违反显式/可测/单一职责，且把权限知识泄漏进 loop。

### D6. 优雅降级统一走既有 `[REPLY]` 兜底
LLM 调用耗尽、预算/打转终止，统一复用 `_FALLBACK_REPLY` 语义（`agent_loop.py:31`），以 `[REPLY]` 前缀 yield。不新增前缀，Channel/前端无需改动。

## Risks / Trade-offs

- **[token 估算不准]** → 明确为"防失控上限"非计费；阈值设宽松默认值，Phase 6 再用真实 trace 校准。
- **[默认放行的权限策略看似没护栏]** → 机制（标记+闸门+回灌）就位且有测试覆盖 deny 路径；默认放行是为不破坏现有 e2e/evals，策略可在部署时注入收紧。
- **[retry 把幂等性问题放大]** → 仅对 LLM 调用（只读、幂等）重试；**绝不**对工具调用尤其 `create_appointment`（有副作用）重试，避免重复下单。在 spec 与测试中固化这一点。
- **[退避真 sleep 拖慢测试]** → sleep 注入化，测试用 no-op。
- **[拆文件粒度争议]** → 见 Open Question，apply 前由人审定。

## Migration Plan

增量、可回滚：护栏均为新增文件 + 对 `agent_loop`/`registry`/`base`/`appointment` 的小改。默认策略放行 + 默认预算宽松 ⇒ 行为对既有 evals 等价。回滚 = 还原这几个文件的 diff，删 `harness/guardrails/`。

## Open Questions

- **OQ1**：`retry.py`（含 timeout）单文件 vs 拆 `timeout.py`+`retry.py` 两文件？倾向单文件（D2），请人审定。
- **OQ2**：token 预算默认值与打转 `repeat_limit` 默认值（暂定 budget 宽松、repeat=3），是否需要可配置入口（如 `AgentLoop` 构造参数）？倾向作为构造参数注入、给安全默认。
