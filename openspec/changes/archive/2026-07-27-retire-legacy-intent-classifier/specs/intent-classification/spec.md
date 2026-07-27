# intent-classification 规格增量

## REMOVED Requirements

### Requirement: 意图分类返回受约束的枚举
**Reason**: 独立意图分类器已退出主服务链路——harness 的 TAO 循环经工具选择完成路由，"意图理解"由工具调用行为隐式承载，独立分类组件不再服务任何用户路径；保留它使门禁守护假目标、误导代码读者。
**Migration**: 无调用方需迁移（主链路 `chat_handler → AgentLoop` 本就不经过它；`api/task.py` 端点随本变更一并删除，实现前需确认无外部调用方）。意图路由质量此后由 eval-harness 的工具调用指标（name 级 F1 等）度量。

### Requirement: 分类异常时安全降级
**Reason**: 随组件本体退役，其降级行为不再有存在对象。
**Migration**: harness 主链路的 LLM 调用失败降级由 `harness/guardrails`（`guarded_invoke` / `GuardrailExhausted` → AgentLoop 兜底回复）承担，已有独立规格（guardrails 能力）约束。
