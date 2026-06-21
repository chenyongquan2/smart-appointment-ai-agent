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

`AgentLoop` 每轮请求 SHALL 注入该会话的对话历史，并在本轮结束后把用户输入与最终回复追加回会话历史。`window_turns`（N 可配置）SHALL 用于**约束压缩触发节奏**（写侧据此判断哪些较旧回合属于「窗外」、可被压缩），但 **MUST NOT** 再作为读侧可见性的硬上限——读侧的可见性分界改由摘要覆盖游标 `covered_upto` 决定（见「读侧上下文组装无夹缝盲区」需求）。即：尚未被摘要覆盖的回合，无论是否超出 `window_turns`，都 SHALL 以原文注入；已被覆盖的较旧回合以摘要形式注入。

#### Scenario: 多轮对话注入历史

- **WHEN** 同一会话第二轮请求到达
- **THEN** `AgentLoop` 在构造 messages 时包含第一轮的用户输入与助手回复，使 LLM 能基于上文作答

#### Scenario: 超出窗口但尚未被压缩的旧回合仍以原文注入

- **WHEN** 会话历史回合数超过 `window_turns`，但超出部分中存在尚未被摘要覆盖（id > `covered_upto`）的回合
- **THEN** 这些回合 SHALL 仍以**原文**注入本次 messages（不因超出 `window_turns` 而被丢弃），直到它们被压缩进摘要为止

### Requirement: 长期偏好记忆接入

系统 SHALL 提供一个 `LongTermMemory` 薄封装，跨会话读取既有 `UserBehaviorRepository` 中该用户的高置信度偏好，并作为系统提示补充供 `AgentLoop` 使用。该封装 MUST NOT 重写或修改既有偏好业务逻辑，仅做读取与组装。

#### Scenario: 读取用户偏好注入系统提示

- **WHEN** 一个已有偏好记录的用户发起会话
- **THEN** `LongTermMemory` 读取其高置信度偏好并组装为提示补充，供本次请求的系统提示使用

#### Scenario: 无偏好时不影响流程

- **WHEN** 用户没有任何偏好记录
- **THEN** `LongTermMemory` 返回空补充，请求照常进行，不报错

### Requirement: 摘要记忆层（生产级压缩）

系统 SHALL 提供一个实现 `SummaryMemory` 契约的生产级压缩实现，当会话上下文体量超过配置阈值时，把短期窗口外的较旧回合压缩为一段保留关键信息的摘要文本，供 `AgentLoop` 注入上下文（位置在系统提示之后、短期窗口之前）。`SummaryMemory` 接口签名 MUST NOT 变更，上层调用契约保持零破坏。本实现 MUST 满足以下行为：

- **触发**：系统 SHALL 以 token 预算为主触发条件（复用 `estimate_tokens` 估算窗外回合体量），并 MAY 以窗口轮数作为粗略兜底；未超阈值时 MUST NOT 触发压缩（返回不产生摘要）。
- **结构化内容**：摘要 SHALL 通过 structured output 产出，至少保留「关键实体 / 已做决策 / 未完成事项 / 用户约束（含预约槽位）」，再渲染为提示文本；MUST NOT 因压缩而静默丢弃这些关键字段。
- **滚动压缩**：已存在前序摘要时，系统 SHALL 基于「前序摘要 + 新出窗回合」增量生成新摘要（summary-of-summary），MUST NOT 每次对全部历史重新全量总结。
- **缓存与失效**：摘要 SHALL 被持久化并在覆盖范围未变时命中复用；当被覆盖的历史发生变更（追加/截断/分叉）导致摘要不再匹配时，系统 MUST 使其失效并重算。
- **容错降级**：当摘要 LLM 调用超时或失败时，系统 SHALL 优雅退回到纯窗口裁剪（等价于不注入摘要），MUST NOT 让异常冒泡崩溃 `AgentLoop`。
- **可观测**：每次压缩动作 SHALL 经 `tracer` 记录触发原因、压缩前后近似 token、耗时与是否降级。

关键长期偏好仍归 `LongTermMemory` 跨会话管理，MUST NOT 依赖对话摘要兜底；短期窗口（`ShortTermMemory`）职责不变。

#### Scenario: 未超阈值不触发压缩

- **WHEN** 会话窗外回合的估算 token 未超过配置阈值
- **THEN** `SummaryMemory` 不调用 LLM、不产生摘要，本轮上下文仅含系统提示、短期窗口与当前输入，行为与压缩前一致

#### Scenario: 超阈值时压缩窗外回合并注入摘要

- **WHEN** 会话窗外较旧回合的估算 token 超过配置阈值
- **THEN** 系统把这些窗外回合压缩为结构化摘要，并将其渲染文本注入到本轮上下文（系统提示之后、短期窗口之前），使 LLM 能据早期约束作答

#### Scenario: 摘要保留关键约束不丢失

- **WHEN** 早期回合包含用户约束（如性别偏好、时间限制）或未完成的预约槽位，且这些回合已滑出短期窗口并被压缩
- **THEN** 生成的摘要仍包含这些关键约束/未完成槽位，后续轮次的回复不与这些早期约束冲突

#### Scenario: 滚动增量压缩

- **WHEN** 已存在覆盖较早回合的前序摘要，且又有新回合滑出短期窗口触发再次压缩
- **THEN** 系统基于「前序摘要 + 新出窗回合」生成新摘要，而非对全部历史重新全量总结

#### Scenario: 缓存命中复用

- **WHEN** 同一会话连续多轮请求且摘要覆盖的历史范围未变
- **THEN** 系统复用已持久化的摘要、不重复调用 LLM 生成相同摘要

#### Scenario: LLM 失败时降级到窗口裁剪

- **WHEN** 压缩所需的 LLM 调用超时或抛出异常
- **THEN** `SummaryMemory` 不抛异常、不注入摘要，请求退回到纯短期窗口行为并照常完成；降级动作被记录

#### Scenario: 压缩动作可观测

- **WHEN** 一次压缩被触发
- **THEN** `tracer` 记录该动作的触发原因、压缩前后近似 token、耗时及是否走了降级路径

### Requirement: 会话历史持久化与重启恢复

系统 SHALL 通过新增的 `ConversationTurn` 模型与 `ConversationRepository`（复用既有 SQLite + SQLAlchemy 与 `SessionManager`）把会话对话历史持久化到数据库。进程重启后，按同一 `session_id` 再次请求时 MUST 能从持久化存储恢复该会话的历史。`ConversationRepository` MUST 与既有 Repository 风格一致（经 `session_scope` 管理事务），且 MUST NOT 修改既有 Repository 的实现。

#### Scenario: 重启后按 session_id 恢复历史

- **WHEN** 某会话进行若干轮后进程重启，随后用同一 `session_id` 再次请求
- **THEN** 系统从数据库读回该会话的历史并注入上下文，对话得以延续

#### Scenario: 历史落库

- **WHEN** 一轮对话结束
- **THEN** 该轮的用户输入与助手回复被写入 `ConversationTurn` 表，可被后续查询读回

### Requirement: 读侧上下文组装无夹缝盲区

系统在每轮请求组装上下文时 SHALL 保证：**每一条历史回合要么以摘要形式、要么以原文形式出现在注入给 LLM 的上下文中，不存在「既不在摘要、也不在原文」的回合**。可见性分界为摘要覆盖游标 `covered_upto`：

- id ≤ `covered_upto` 的回合：已被压缩，以**摘要文本**注入（独立 `SystemMessage`，置于 history 首条）；
- id > `covered_upto` 的回合：尚未被压缩，一律以**原文**注入。

读侧为获得稳定的 turn id 以执行该分界，SHALL 从持久层（`ConversationRepository` 或等价）读取 id-bearing 历史。无摘要缓存时 `covered_upto` 视作 0（全部历史以原文注入）。本需求 MUST NOT 改变写侧压缩的触发逻辑与阈值。

#### Scenario: 夹缝回合不再对 LLM 不可见

- **WHEN** 某回合已掉出 `window_turns` 窗口，但尚未触发压缩（covered_upto < 其 id ≤ 窗口边界）
- **THEN** 该回合 SHALL 以原文出现在本轮注入 LLM 的上下文中（而非既不在摘要也不在原文）

#### Scenario: 已压缩回合以摘要替代原文，不重复

- **WHEN** 某回合的 id ≤ `covered_upto`（已被压缩进摘要）
- **THEN** 它 SHALL 以摘要形式注入，且其原文 MUST NOT 再被重复注入

#### Scenario: 无摘要缓存时全部原文注入

- **WHEN** 该会话尚无摘要缓存（covered_upto 视作 0）
- **THEN** 全部历史回合以原文注入；因首次压缩前历史长度存在上界（约 `window_turns + min_old_turns`），上下文不会无界膨胀
