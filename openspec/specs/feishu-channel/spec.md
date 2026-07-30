# feishu-channel Specification

## Purpose

定义飞书（Lark）IM 接入通道：以长连接模式订阅群消息事件，把 @bot 的消息解析为稳定的会话键与用户身份后提交给 task-executor，并把任务终态以富文本回复投递回原会话。通道只做「事件 → 任务」与「终态 → 回复」的翻译，不解析 Agent 的输出协议、不承载业务逻辑。

## Requirements

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

### Requirement: 会话键解析与会话映射

系统 SHALL 从消息事件解析出稳定的会话键。会话作用域 SHALL 可配置：

- `reply`（**默认**）：解析顺序 `root_id → message_id`（取首个非空者）。语义为「一次 @bot 开一条会话，在该消息下回复即继续同一会话」。
- `chat`：直接用 `chat_id`，整群共用一条会话。

session_id 命名为 `feishu:{解析出的键}`。同一会话内的多轮消息 MUST 共享同一会话记忆，不同会话 MUST 相互隔离。映射 SHALL 持久化（进程重启不丢），存储的是**解析后**的键。

`thread_id` MUST NOT 参与会话键的选取（可作为排障字段记入日志）。理由是实测得出的硬约束（证据见 `docs/evidence/feishu-event-payload-2026-07-29.log`）：

| 消息 | `thread_id` | `root_id` | `message_id` |
|---|---|---|---|
| 首条 @bot 消息 | **无** | **无** | 有 |
| 对某条消息的回复 | 有（飞书自动建话题） | 有（= 被回复消息的 id） | 有 |

即 `thread_id` **只出现在续话消息上、首条没有**。若把它排在解析链首位，首条消息会落到 `feishu:{message_id}`、其回复却落到 `feishu:{thread_id}`——两者不同，多轮直接断裂。而 `root_id → message_id` 天然自洽：首条取自身 `message_id`，其后每条回复的 `root_id` 都指回那条首条消息。

由此 `reply` 作用域依赖回复链，故「用户可见 ack」MUST 以回复（reply）方式发送——机器人的 ack 因此挂进同一条链，用户回复 ack 时 `root_id` 仍指向最初那条消息，会话不变。

非目标：真话题模式群（首条消息即带 `thread_id`）的专用作用域**不在本变更范围内**——尚无可用于验证的话题群，加一个未经实测的模式比不加更糟。届时新增 `thread` 作用域即可，不影响上述两种。

#### Scenario: 回复即续话
- **WHEN** 用户 @bot 发一条消息，随后回复该消息（或回复 bot 对它的 ack）
- **THEN** 两条消息解析出同一会话键，第二条的处理能引用第一条的上下文

#### Scenario: 各自独立的 @ 互不干扰
- **WHEN** 用户在同一群内两次独立 @bot（都不是回复）
- **THEN** 两者解析出不同会话键，记忆互不可见

#### Scenario: thread_id 不参与取键
- **WHEN** 收到一条同时带 `thread_id` 与 `root_id` 的回复消息
- **THEN** 会话键取自 `root_id`，`thread_id` MUST NOT 影响结果

#### Scenario: 整群作用域
- **WHEN** 作用域配置为 `chat`
- **THEN** 同群所有消息解析出同一会话键（`chat_id`），不区分回复关系

### Requirement: 用户身份传递
系统 SHALL 从事件中取发送者的 `open_id`（`sender.sender_id.open_id`），作为 `user_id` 随任务提交，使长期偏好按人隔离；会话历史仍按会话键共享。

MUST NOT 依赖 `sender.sender_id.user_id`——实测该字段在未开通通讯录权限时不下发（证据见 `docs/evidence/feishu-event-payload-2026-07-29.log`），而 `open_id` 恒有值。

#### Scenario: 群内多人发言
- **WHEN** 同一会话内两位成员先后 @bot
- **THEN** 两条消息进入同一会话历史，但各自携带不同 user_id

### Requirement: @bot 判定
系统 SHALL 通过比对 `message.mentions[].id.open_id` 与**机器人自身的 open_id** 判定本条消息是否 @ 了自己；机器人自身 open_id SHALL 在启动时从开放平台接口取得或经配置注入。

MUST NOT 以 `mentioned_type == "bot"` 判定（群内存在其它机器人时会误判），MUST NOT 以 `name` 匹配（机器人改名即失效）。

#### Scenario: 群内有多个机器人
- **WHEN** 群消息 @ 的是另一个机器人
- **THEN** 系统忽略该消息，不提交任务、不回复

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

### Requirement: 回复发进话题且渲染富文本

机器人的所有回复（ack、结果、各类提示）SHALL 以**发进话题**的方式发送（飞书 `reply_in_thread`），使触发消息成为话题根、一问一答连同后续追问收进同一话题，主聊天流只留一条折叠入口。

任务结果 SHALL 以支持 markdown 渲染的富文本形式投递（交互式卡片的 `lark_md`）。markdown 中飞书不支持的语法 SHALL 降级为支持的等价形式（如标题降级为加粗），其余 MUST 原样透传——MUST NOT 因转换而丢失或改写正文内容。

理由（实测）：改造前用引用回复 + 纯文本，群里表现为一问一答平铺、每条机器人消息头上顶一遍被引用的原文，消息一多就难以追踪；且 Agent 输出的 `**加粗**` 原样显示为字面星号。两者都不影响功能，但直接损害可用性——而「在 IM 里真的能用」正是本变更的目标。

「不认的降级、其余透传」而非做完整 markdown 转换：Agent 的输出格式本就不稳定，转换越复杂越容易在边缘情形改坏正文。宁可少渲染，不可弄丢内容。

#### Scenario: 回复收进同一话题
- **WHEN** 用户 @bot 发一条消息，随后在该话题内继续追问
- **THEN** ack、结果与后续往来都出现在同一话题内，主聊天流不被逐条平铺

#### Scenario: markdown 被渲染而非显示为字面标记
- **WHEN** Agent 的回复含 `**加粗**`
- **THEN** 用户看到的是加粗文字，而非字面的星号

#### Scenario: 不支持的语法降级但不丢内容
- **WHEN** Agent 的回复含 markdown 标题（如 `## 服务咨询`）
- **THEN** 该行以加粗呈现，标题文字本身完整保留

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
