# feishu-channel 规格

## ADDED Requirements

### Requirement: 长连接事件订阅
系统 SHALL 通过飞书长连接模式订阅 `im.message.receive_v1` 事件接收群消息，MUST NOT 要求公网回调地址。接入域名 SHALL 可配置（默认 `open.feishu.cn`，兼容 `open.larksuite.com`）。接入 SHALL 由环境变量开关控制，默认关闭。

#### Scenario: 收到群内 @bot 消息
- **WHEN** 群成员在群里 @bot 并发送文本消息
- **THEN** 系统在长连接上收到该事件并进入处理流程

#### Scenario: 非 @bot 消息忽略
- **WHEN** 群消息未 @bot
- **THEN** 系统 MUST 忽略该消息，不提交任务、不回复

### Requirement: 事件去重（防重复副作用）
系统 SHALL 按 event_id 对飞书事件去重；同一 event_id 重复投递 MUST 只处理一次。去重表 SHALL 有 TTL（默认 5 分钟）与容量上限，MUST NOT 无界增长。

理由（不是性能权衡）：`create_appointment` 等危险工具**没有幂等键**，重复消费一次事件等于真的多下一单。事件去重是本变更中防止重复副作用的唯一防线，MUST NOT 因「重投窗口短」而省略。进程重启后去重表清空、存在极小概率的重复消费，属已记账的残余风险。

#### Scenario: 重复投递
- **WHEN** 同一 event_id 的事件被投递两次
- **THEN** 系统只提交一个任务，且只产生一次 ack 与一次结果回复

#### Scenario: 去重表不无界增长
- **WHEN** 长时间运行并持续收到事件
- **THEN** 去重表按 TTL 与容量上限淘汰旧条目，内存占用有界

### Requirement: 会话键解析与话题到会话的映射

系统 SHALL 从消息事件解析出稳定的会话键，解析顺序为 `thread_id → root_id → message_id`（取首个非空者）；会话作用域 SHALL 可配置（`thread` 默认 / `chat` 整群共用一条会话）。session_id 命名为 `feishu:{解析出的键}`。同一会话内的多轮消息 MUST 共享同一会话记忆，不同会话 MUST 相互隔离。映射 SHALL 持久化（进程重启不丢），存储的是**解析后**的键。

理由：`thread_id` 仅在开启话题模式的群中下发，普通群内 @bot 的消息只有 `chat_id` / `message_id` / 回复链的 `root_id`。直接以 `thread_id` 作会话键在普通群会取到空值。默认 `thread` 作用域的语义是「一次 @bot 开一条会话，在该消息下回复继续多轮」，既贴合飞书交互习惯，也避免整群成员共用一条历史而互相串味。

实施约束：本条的字段可用性判断 MUST 在真实租户以一条真实消息的事件载荷验证后再落 DB 结构，验证 MUST 先于映射表的建表实施。

#### Scenario: 同话题多轮
- **WHEN** 用户在同一话题（或同一回复链）内先后发送两条消息
- **THEN** 第二条消息的处理能引用第一条的上下文

#### Scenario: 跨话题隔离
- **WHEN** 两个不同话题各发送一条消息
- **THEN** 两者使用不同 session_id，记忆互不可见

#### Scenario: 普通群消息无 thread_id 时的回退
- **WHEN** 收到的消息事件不含 `thread_id`
- **THEN** 系统按 `root_id → message_id` 回退取键，不因字段缺失而失败或落到空会话键

### Requirement: 用户身份传递
系统 SHALL 从事件中取发送者的 open_id，作为 `user_id` 随任务提交，使长期偏好按人隔离；会话历史仍按会话键共享。

#### Scenario: 群内多人发言
- **WHEN** 同一话题内两位成员先后 @bot
- **THEN** 两条消息进入同一会话历史，但各自携带不同 user_id

### Requirement: 双层 ack

系统 SHALL 区分两层 ack，两者都 MUST 做到：

- **协议 ack**：事件处理回调 MUST 立即返回，MUST NOT 等待任务执行结果（飞书要求事件在秒级内被确认）。
- **用户可见 ack**：SHALL 对触发消息回复一条「处理中」提示。SHALL 使用回复（reply）而非表情回应，以便同时建立会话键解析所依赖的回复链。

顺序为：提交任务 → 发送用户可见 ack → 事件回调返回。用户可见 ack 投递失败 SHALL 记录结构化日志，MUST NOT 影响已提交任务的执行。

#### Scenario: 长任务先 ack
- **WHEN** 收到一条需要较长处理时间的消息
- **THEN** 用户先在话题内收到「处理中」提示，处理完成后再收到结果

#### Scenario: 事件回调不阻塞
- **WHEN** 任务需要数分钟才能完成
- **THEN** 事件处理回调在提交任务后立即返回，不等待任务终态

### Requirement: 结果投递与绝不静默
任务到达任何终态（成功 / 失败 / 超时 / guardrail 耗尽 / 忙碌拒绝）后，系统 MUST 向原会话投递一条对应回复；投递失败 SHALL 重试（默认 2 次），重试仍失败 SHALL 记录结构化错误日志。用户可感知的流程 MUST NOT 无声结束。

超时文案 MUST 提示副作用风险（若已产生预约请勿重复操作），且系统 MUST NOT 自动重试任务。

#### Scenario: 成功投递
- **WHEN** Agent 处理完成
- **THEN** 结果回复出现在触发消息所在会话内

#### Scenario: 任务失败仍有回复
- **WHEN** 任务执行抛出异常或超时
- **THEN** 原会话内收到一条说明失败/超时的回复

#### Scenario: 忙碌拒绝也有回复
- **WHEN** 该会话排队已满导致任务未入队
- **THEN** 用户收到一条明确的「稍后再试」提示，而非无响应
