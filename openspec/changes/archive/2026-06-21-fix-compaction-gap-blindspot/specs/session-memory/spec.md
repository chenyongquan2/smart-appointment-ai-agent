## MODIFIED Requirements

### Requirement: 短期对话记忆窗口

`AgentLoop` 每轮请求 SHALL 注入该会话的对话历史，并在本轮结束后把用户输入与最终回复追加回会话历史。`window_turns`（N 可配置）SHALL 用于**约束压缩触发节奏**（写侧据此判断哪些较旧回合属于「窗外」、可被压缩），但**MUST NOT** 再作为读侧可见性的硬上限——读侧的可见性分界改由摘要覆盖游标 `covered_upto` 决定（见「读侧上下文组装无夹缝盲区」需求）。即：尚未被摘要覆盖的回合，无论是否超出 `window_turns`，都 SHALL 以原文注入；已被覆盖的较旧回合以摘要形式注入。

#### Scenario: 多轮对话注入历史

- **WHEN** 同一会话第二轮请求到达
- **THEN** `AgentLoop` 在构造 messages 时包含第一轮的用户输入与助手回复，使 LLM 能基于上文作答

#### Scenario: 超出窗口但尚未被压缩的旧回合仍以原文注入

- **WHEN** 会话历史回合数超过 `window_turns`，但超出部分中存在尚未被摘要覆盖（id > `covered_upto`）的回合
- **THEN** 这些回合 SHALL 仍以**原文**注入本次 messages（不因超出 `window_turns` 而被丢弃），直到它们被压缩进摘要为止

## ADDED Requirements

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
