## MODIFIED Requirements

### Requirement: 保留流式编排接口与会话参数

替换硬路由后，请求编排入口 `ProcessUserInput_stream` SHALL 仍以异步流式 `yield` 输出供既有 Channel 层消费，并保留既有的 `[THOUGHT]` / `[REPLY]` / `[ERROR]` 前缀语义，调用方无需改动既有前缀解析。`ProcessUserInput_stream` SHALL 接受一个可选 `session_id` 参数并据此选用按会话隔离的状态与记忆。`AgentLoop.run()` SHALL 使用其 `session_id` 参数关联到对应会话的对话历史，注入该会话的短期记忆窗口，并在回合结束后回写历史；MUST NOT 再每次请求都从零构建上下文而丢弃多轮记忆。

#### Scenario: 流式接口向后兼容

- **WHEN** 既有 Channel 层调用 `ProcessUserInput_stream(user_input)`（不带 session_id）
- **THEN** 它仍异步逐段 `yield` 文本，服务端为其分配会话，`AgentLoop` 由其内部驱动，既有前缀语义不变

#### Scenario: 带 session_id 时关联会话记忆

- **WHEN** `ProcessUserInput_stream(user_input, session_id=s)` 在同一 `s` 上被多次调用
- **THEN** 第二次及以后的调用，`AgentLoop` 注入会话 `s` 之前回合的历史，使回复体现多轮上下文
