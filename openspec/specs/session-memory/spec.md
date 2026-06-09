# session-memory Specification

## Purpose

定义 harness 运行时的会话状态与记忆能力：按 `session_id` 隔离每个会话的状态，向 `AgentLoop` 注入短期对话记忆窗口与跨会话的长期偏好，约定（并以 stub 形式预留）超窗口回合的摘要压缩接口，并把会话历史持久化到数据库以支持进程重启后的恢复。它复用既有 SQLite + SQLAlchemy、`SessionManager` 与 `UserBehaviorRepository`，不重写既有业务逻辑，仅做隔离、读取与组装。

## Requirements

### Requirement: 按 session_id 隔离会话状态

系统 SHALL 提供一个 `SessionStore`，按 `session_id` 隔离每个会话的状态（至少包含对话历史），不同 `session_id` 之间 MUST NOT 共享或串改对方的状态。请求编排入口 MUST NOT 再使用单一全局 `session_id` 或模块级单例状态服务所有请求。

#### Scenario: 两个会话并发互不干扰

- **WHEN** 两个不同 `session_id` 的请求交替到达，各自进行多轮对话
- **THEN** 每个会话只看到自己的历史，一个会话写入的消息不出现在另一个会话的上下文中

#### Scenario: 缺省 session_id 时服务端生成

- **WHEN** 请求未携带 `session_id`
- **THEN** 服务端为其生成一个新的 `session_id`、为该会话创建独立状态，并随响应回传该 `session_id` 供后续请求复用

### Requirement: 短期对话记忆窗口

`AgentLoop` 每轮请求 SHALL 注入该会话最近的对话历史（短期记忆），并在本轮结束后把用户输入与最终回复追加回会话历史。系统 SHALL 保留最近 N 轮的窗口（N 可配置），超出窗口的较旧回合 MUST NOT 注入到 LLM 上下文（仍可被持久化保留）。

#### Scenario: 多轮对话注入历史

- **WHEN** 同一会话第二轮请求到达
- **THEN** `AgentLoop` 在构造 messages 时包含第一轮的用户输入与助手回复，使 LLM 能基于上文作答

#### Scenario: 超出窗口的旧回合不注入

- **WHEN** 会话历史回合数超过配置的窗口 N
- **THEN** 仅最近 N 轮被注入 LLM 上下文，更早的回合不出现在本次 messages 中

### Requirement: 长期偏好记忆接入

系统 SHALL 提供一个 `LongTermMemory` 薄封装，跨会话读取既有 `UserBehaviorRepository` 中该用户的高置信度偏好，并作为系统提示补充供 `AgentLoop` 使用。该封装 MUST NOT 重写或修改既有偏好业务逻辑，仅做读取与组装。

#### Scenario: 读取用户偏好注入系统提示

- **WHEN** 一个已有偏好记录的用户发起会话
- **THEN** `LongTermMemory` 读取其高置信度偏好并组装为提示补充，供本次请求的系统提示使用

#### Scenario: 无偏好时不影响流程

- **WHEN** 用户没有任何偏好记录
- **THEN** `LongTermMemory` 返回空补充，请求照常进行，不报错

### Requirement: 摘要记忆层接口（本 Phase 留 stub）

系统 SHALL 定义一个 `SummaryMemory` 接口，约定当会话历史超过窗口阈值时对较旧回合进行压缩的契约。本 Phase MUST 仅提供接口与一个不做实际压缩的占位实现（no-op 或简单截断），并在文档中写明触发条件，真正的压缩逻辑留待后续 Phase。

#### Scenario: 占位实现不破坏行为

- **WHEN** 会话历史增长并触发摘要接口
- **THEN** 占位 `SummaryMemory` 按约定返回（不丢失短期窗口内的回合、不抛异常），整体对话流程不受影响

### Requirement: 会话历史持久化与重启恢复

系统 SHALL 通过新增的 `ConversationTurn` 模型与 `ConversationRepository`（复用既有 SQLite + SQLAlchemy 与 `SessionManager`）把会话对话历史持久化到数据库。进程重启后，按同一 `session_id` 再次请求时 MUST 能从持久化存储恢复该会话的历史。`ConversationRepository` MUST 与既有 Repository 风格一致（经 `session_scope` 管理事务），且 MUST NOT 修改既有 Repository 的实现。

#### Scenario: 重启后按 session_id 恢复历史

- **WHEN** 某会话进行若干轮后进程重启，随后用同一 `session_id` 再次请求
- **THEN** 系统从数据库读回该会话的历史并注入上下文，对话得以延续

#### Scenario: 历史落库

- **WHEN** 一轮对话结束
- **THEN** 该轮的用户输入与助手回复被写入 `ConversationTurn` 表，可被后续查询读回
