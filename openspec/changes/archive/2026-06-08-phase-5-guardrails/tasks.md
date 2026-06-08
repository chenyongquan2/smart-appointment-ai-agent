## 1. LLM 调用护栏（超时 + 重试）

- [x] 1.1 新建 `harness/guardrails/__init__.py` 与 `harness/guardrails/retry.py`：定义 `GuardrailExhausted` 异常与 async `guarded_invoke`（`asyncio.wait_for` 超时 + 指数退避重试可重试异常，可注入 `sleep`），耗尽抛 `GuardrailExhausted`
- [x] 1.2 `tests/` 新增 retry 单测：首次成功不重试、瞬时失败后重试成功、超时触发重试、耗尽抛 `GuardrailExhausted`；退避用 no-op sleep，全程不触网
- [x] 1.3 `AgentLoop.run` 改为经 `guarded_invoke` 调用 LLM；捕获 `GuardrailExhausted` 转 `[REPLY]` 兜底回复（新增的"LLM 持续失败时优雅降级"场景）

## 2. Loop 预算与打转护栏

- [x] 2.1 新建 `harness/guardrails/budget.py`：token 近似估算（字符数/4 累计）与 `max_tokens` 上限判定 + 连续相同 `(name, args)` 的 `repeat_limit` 打转检测（纯函数/小状态对象，易测）
- [x] 2.2 `AgentLoop` 接受 `max_tokens` / `repeat_limit` 构造参数（安全默认），在循环内接入预算与打转终止，触达即 `[REPLY]` 兜底
- [x] 2.3 `tests/` 新增预算与打转单测：预算耗尽终止、预算充足不干预、连续相同调用触发终止、参数不同不算打转

## 3. 危险操作权限闸门

- [x] 3.1 `harness/tools/base.py`：`Tool` 加 `dangerous: bool = False`（向后兼容）
- [x] 3.2 `harness/tools/appointment.py`：`create_appointment` 标记 `dangerous=True`；确认只读工具保持默认 `False`
- [x] 3.3 新建 `harness/guardrails/permission.py`：定义结构化 `Decision`（allow/deny + reason）与权限策略协议；默认放行策略
- [x] 3.4 `harness/tools/registry.py`：`ToolRegistry` 接受可选 `permission` 策略；`dispatch` 对 `dangerous` 工具先问策略，deny 时不执行 handler、返回结构化拒绝结果
- [x] 3.5 `tests/` 新增权限单测：危险工具被拒不执行 handler、被放行正常执行、无策略默认放行、危险标记正确

## 4. 错误隔离回归 + 端到端降级

- [x] 4.1 `tests/` 补"工具失败回灌不崩 loop"显式回归测试（覆盖既有 `agent_loop.py` 错误回灌）+ "权限拒绝结果回灌"场景
- [x] 4.2 `AgentLoop` 确认副作用工具（`create_appointment`）不被 LLM 重试护栏波及（重试仅包裹 LLM 调用），加断言性测试
- [x] 4.3 跑 `uv run pytest` 与（若有运行器）`uv run python evals/run_evals.py`，确保全绿、注入坏输入/超时/异常/拒绝时 harness 不崩
