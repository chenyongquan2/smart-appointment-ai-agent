# feishu-channel 规格

## ADDED Requirements

### Requirement: 长连接事件订阅
系统 SHALL 通过飞书长连接模式订阅 `im.message.receive_v1` 事件接收群消息，MUST NOT 要求公网回调地址。接入域名 SHALL 可配置（默认 `open.feishu.cn`，兼容 `open.larksuite.com`）。

#### Scenario: 收到群内 @bot 消息
- **WHEN** 群成员在群里 @bot 并发送文本消息
- **THEN** 系统在长连接上收到该事件并进入处理流程

#### Scenario: 非 @bot 消息忽略
- **WHEN** 群消息未 @bot
- **THEN** 系统 MUST 忽略该消息，不提交任务、不回复

### Requirement: 事件去重（幂等）
系统 SHALL 按 event_id 对飞书事件去重；同一 event_id 重复投递 MUST 只处理一次。

#### Scenario: 重复投递
- **WHEN** 同一 event_id 的事件被投递两次
- **THEN** 系统只提交一个任务，且只产生一次 ack 与一次结果回复

### Requirement: 话题到会话的映射
系统 SHALL 将飞书话题映射为 Agent 会话，session_id 形如 `feishu:{thread_id}`；同一话题内的多轮消息 MUST 共享同一会话记忆，不同话题 MUST 相互隔离。映射 SHALL 持久化（进程重启不丢）。

#### Scenario: 同话题多轮
- **WHEN** 用户在同一话题内先后发送两条消息
- **THEN** 第二条消息的处理能引用第一条的上下文

#### Scenario: 跨话题隔离
- **WHEN** 两个不同话题各发送一条消息
- **THEN** 两者使用不同 session_id，记忆互不可见

### Requirement: 秒回 ack
系统 SHALL 在收到有效消息后立即回复处理中提示（ack），再提交任务；ack MUST NOT 等待 Agent 处理完成。

#### Scenario: 长任务先 ack
- **WHEN** 收到一条需要较长处理时间的消息
- **THEN** 用户先在话题内收到"处理中"提示，处理完成后再收到结果

### Requirement: 结果投递与绝不静默
任务到达任何终态（成功/失败/超时）后，系统 MUST 向原话题投递一条对应回复；投递失败 SHALL 重试，重试仍失败 SHALL 记录结构化错误日志。用户可感知的流程 MUST NOT 无声结束。

#### Scenario: 成功投递
- **WHEN** Agent 处理完成
- **THEN** 结果回复出现在触发消息所在话题内

#### Scenario: 任务失败仍有回复
- **WHEN** 任务执行抛出异常或超时
- **THEN** 原话题内收到一条说明失败/超时的回复
