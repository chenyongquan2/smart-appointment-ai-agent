## MODIFIED Requirements

### Requirement: 评估用例集对齐真实意图口径

评估集 SHALL 以 `输入 → 期望行为` 为用例，其文件位置为**当前装载领域包**声明的 `evals_dir/cases.jsonl`（见 `domain-packages`）。用例的 `expected_intent` MUST 取自**该领域包声明的标签集合**（`EvalProfile.labels`）之一；运行器 MUST NOT 内置任何具体领域的标签白名单。该标签为**数据集构成元数据**（用于覆盖约束、按类分项分析与 dev/held-out 切分规则），SHALL NOT 被理解为对某个分类器组件的依赖，且**跨域标签 SHALL NOT 混用或互相比较**。

预约域声明的标签集合为 5 类：`appointment`、`query`、`pay`、`statistics`、`other`；其用例集 SHALL 覆盖全部 5 类，并包含边界场景（多槽位、缺槽位追问、改约、与服务无关的输入）。

用例集 SHALL 划分为 **dev** 与 **held-out** 两个子集（集归属规则见「用例集 dev / held-out 切分」需求）。**各域的规模下限由该域自己的能力规格声明**；全集（dev + held-out）总量 SHALL 不少于 18 条（向后兼容既有下限），且 held-out 子集总量 SHALL 不少于 10 条。预约域的现行下限为：dev 子集不少于 40 条且每一类意图不少于 5 条，held-out 子集不少于 10 条并至少覆盖 3 类意图。

用例的「输入」SHALL 支持两种形态，二者向后兼容：

- **单轮**：`input` 为单条用户话语字符串（既有形态，不变）。
- **多轮**：`turns` 为有序的用户话语字符串列表（每个元素是一轮用户输入）。一条用例 SHALL 提供 `input` 与 `turns` 之一；同时提供时 MUST 报错指出行号。单轮 `input` 在语义上等价于单元素 `turns`。

无论单轮还是多轮，`expected_intent` MUST 取自该域声明的标签集合；多轮用例的 `expected_tools` / `expected_slots`（若标注）的口径为**整段对话累计**——即期望工具序列/期望槽位键集为跨所有轮次合并后的集合，与既有单轮口径在「单元素 turns」上自然一致。

#### Scenario: 用例标签取值合法

- **WHEN** 加载当前域 `cases.jsonl` 中任一非注释用例
- **THEN** 其 `expected_intent` 必须是**该域声明的标签集合**之一，否则运行器报错并指出行号

#### Scenario: 运行器不内置领域标签

- **WHEN** 检视 `evals/run_evals.py`
- **THEN** 其中不存在任何写死的具体领域标签名，标签白名单一律经装载的领域包取得

#### Scenario: 预约域五类全覆盖

- **WHEN** 统计预约域用例集的 `expected_intent` 分布
- **THEN** 其声明的 5 个类目每个至少出现一次

#### Scenario: dev 子集规模与每类下限

- **WHEN** 统计某域 dev 子集的用例数与按标签分布
- **THEN** 满足该域能力规格声明的规模下限（预约域为总量不少于 40 条、每类不少于 5 条）

#### Scenario: held-out 子集规模与覆盖

- **WHEN** 统计 held-out 子集的用例数与标签覆盖
- **THEN** held-out 子集总量不少于 10 条并至少覆盖 3 类标签

#### Scenario: 注释与空行被跳过

- **WHEN** 文件含 `//` 开头的注释行或空行
- **THEN** 运行器加载时跳过它们，不计入用例

#### Scenario: 多轮用例以 turns 列表表达

- **WHEN** 一条用例提供 `turns`（字符串列表）而非 `input`
- **THEN** 运行器 SHALL 加载该用例并按多轮路径评估，其 `expected_intent` 校验与单轮用例一致

#### Scenario: input 与 turns 互斥

- **WHEN** 一条用例同时提供了 `input` 与 `turns`（或两者皆缺）
- **THEN** 运行器 SHALL 报错并指出行号，MUST NOT 静默猜测

### Requirement: 槽位采集（actual_slots）从工具调用还原

评估运行器 SHALL 从端到端真跑采集到的工具调用序列（`CaptureResult.tool_calls`，每项含 `name` 与 `args`）**还原**出一份扁平的「实际槽位」dict `actual_slots`，用作 `槽位抽取完整率` 指标的当前值输入。键的归一映射（工具入参名 → 槽位键）SHALL 取自**当前装载领域包**声明的 `EvalProfile.slot_key_map`，运行器与指标模块 MUST NOT 内置任何具体领域的槽位名。预约域声明的映射为 `{start_time → start_time, duration → duration, project → project, preference → preference, gender → gender, technician_name → technician}`。

领域包 MAY 声明**空**的槽位键映射，表示本域不度量槽位完整率；此时该指标对本域恒为 N/A，且 MUST NOT 被列入本域门禁（见「门禁指标集随域声明」）。带 schema 默认值的入参 MUST NOT 被声明为槽位键——默认值恒存在会使完整率虚高，与「哨兵值不算已填」同理。

该还原 SHALL 实现为**纯函数**（吃工具调用列表 + 槽位键映射 → 返回槽位 dict，不触网、不读写文件），可离线确定性单测。

还原规则 SHALL 满足：

- **跨工具合并**：槽位分散在多个工具的 args 中（如 `find_technician.project`、`create_appointment.project`、`check_availability.duration`），还原时 SHALL 把各工具调用中的槽位字段合并进同一份 dict；映射中声明的别名（如 `technician_name`）归一为其槽位键（`technician`）。
- **同名槽位冲突**：同一槽位在多个工具调用中均出现且**取值不同**时，SHALL 采用确定性策略（**后出现的工具调用覆盖先出现的**，即按 `tool_calls` 顺序「last write wins」），MUST NOT 依赖不确定的遍历顺序。
- **哨兵值不算已填**：工具 schema 的可选槽位默认占位串（`未知` / `无`）SHALL 视为「未抽取」而**不写入** `actual_slots`（或等价地不计为命中），使完整率反映模型真正抽到的槽位、不被默认值虚高。
- **无工具调用时**：`tool_calls` 为空或真跑失败（`None`）时，`actual_slots` SHALL 为 `None`，使该用例的槽位指标按既有约定标 N/A，MUST NOT 伪造空 dict 当作「抽取了 0 个槽位」。

#### Scenario: 跨工具合并槽位

- **WHEN** 某用例的工具序列含 `find_technician(project=推拿, gender=male)` 与 `create_appointment(start_time=..., duration=60分钟, project=推拿)`
- **THEN** 还原出的 `actual_slots` 含合并后的 `{project: 推拿, gender: male, start_time: ..., duration: 60分钟}`

#### Scenario: 同名槽位冲突按后者覆盖

- **WHEN** 同一槽位（如 `project`）在两个工具调用中取值不同
- **THEN** 还原结果取**后出现**的工具调用的值（确定性 last-write-wins）

#### Scenario: 哨兵默认值不计为已抽取

- **WHEN** 工具调用中某可选槽位取 schema 默认占位串（`未知` / `无`）
- **THEN** 该槽位不写入 `actual_slots`（不被计为命中），完整率不因默认值虚高

#### Scenario: 无工具调用时槽位标 N/A

- **WHEN** 用例端到端真跑失败或未产生任何工具调用
- **THEN** `actual_slots` 为 `None`，该用例的 `槽位抽取完整率` 标 N/A，不伪造分母

#### Scenario: 域声明空槽位映射时指标恒 N/A

- **WHEN** 当前域声明的 `slot_key_map` 为空
- **THEN** `槽位抽取完整率` 对该域全部用例标 N/A，报告附「本域不度量该项」说明，且该指标不出现在本域被守项中

### Requirement: 预约类用例策展以稳定触发工具链使槽位完整率非 N/A

为使门禁稳定实守该域声明的全部被守项，评估用例集中**喂被守指标的锚点用例** SHALL 以**信息齐全的祈使式单轮输入**为主——即在单轮内同时给出足以触发工具链的关键信息，且表达明确的办理/查询意图，使保守的执行体倾向**直接调用工具办理**而非反问澄清，从而让被守指标的当前值稳定从工具调用中还原出真值。

预约域的具体形态为：带 `expected_slots` 的预约（appointment）类用例至少含时间与项目（并视用例补全 duration / technician / gender / preference），使保守的预约子 Agent（[harness/subagents/appointment.py](../../../harness/subagents/appointment.py) 系统提示「信息不足则追问、不臆测下单」）倾向直接调用工具，让 `actual_slots` 稳定还原。其他域按本域工具形态自行策展等效锚点（如值守域按工具逐个提供锚点用例）。

锚点用例 SHALL 在数量上足够（多条独立用例），使「某次跑中所有相关用例都未触发任何工具」这一导致被守指标整体 N/A 的情形发生概率足够低；在常规门禁跑（含 `--samples N`）下，该域声明的被守指标 SHALL 稳定产出真值并被门禁实守。

本需求 SHALL NOT 改变任何指标的既有口径（如槽位完整率仍为存在性口径），SHALL NOT 改变子 Agent 行为、系统提示或任何 `services/` / `harness/runtime` 业务逻辑——唯一杠杆是用例（数据集）本身。

诚实边界 SHALL 保留：本需求降低而非消除回落概率；当某次跑因 LLM 非确定性致全部相关用例罕见地均未触发工具时，相应指标仍按既有 skipped 语义处理、报告如实给出当次实守项数，MUST NOT 把「稳定守 N 项」表述为「绝对永不回落」。

#### Scenario: 信息齐全的祈使式预约用例具有可观触发概率

- **WHEN** 在 API key 可用时对一条信息齐全的祈使式预约用例（精确时间 + 项目 + 点名具体技师等）多次真跑 `AgentLoop`
- **THEN** 该用例在相当比例的跑次中触发领域工具（如 `find_technician` / `check_availability`），`actual_slots` 从工具调用 args 还原出非 None 的槽位 dict 并计入 `槽位抽取完整率`；单条触发为 LLM 非确定行为、不要求恒触发，故策展靠**足量此类用例的冗余**而非任何单条的确定性

#### Scenario: 常规门禁跑稳定实守该域全部被守项

- **WHEN** 以 `uv run python evals/run_evals.py --gate --samples 3` 运行
- **THEN** 该域声明的被守指标均产出真值（非 N/A），门禁报告如实标注当次实守项数

#### Scenario: 口径与子 Agent 行为不变

- **WHEN** 应用本需求策展用例后检视评估口径与业务代码
- **THEN** 各指标仍按既有口径判定，且 `harness/subagents/` 子 Agent 提示与 `services/` 业务逻辑未被改动

#### Scenario: 罕见全未触发时诚实回落

- **WHEN** 某次跑因 LLM 非确定性致全部锚点用例均未触发任何工具
- **THEN** 相应指标按既有 skipped 语义标「无法比对」，报告如实给出当次实守项数，不据此判失败也不夸大

## ADDED Requirements

### Requirement: 门禁指标集随域声明

门禁守护的指标子集 SHALL 取自**当前装载领域包**声明的 `EvalProfile.gated_metrics`，`evals/metrics.py` MUST NOT 把某一具体领域适用的指标组合写死为全局常量。

声明 SHALL 受以下约束，违反时装载 MUST 失败而非静默降级：

- 声明的每个指标名 MUST 是报告中真实存在的指标名（拼错即装载失败）；
- 分档说明性指标（`工具调用-召回率` / `工具调用-精确率` 等同一底层行为的冗余档）与 `端到端延迟`、`回复质量通过率` MUST NOT 被声明为被守项——前者是同一信号算多遍，后二者分别是环境噪声与未校准 judge；
- 声明为空集 MUST 失败——「一个都不守」等于没有门禁，必须显式暴露而非默许。

预约域声明为 `{工具调用-F1, 槽位抽取完整率}`（与本变更前的全局常量等值，故其行为与基线数字不变）。

#### Scenario: 门禁按域取被守项

- **WHEN** 在某域下以 `--gate` 运行
- **THEN** 被守指标为该域 `EvalProfile.gated_metrics` 声明的集合，报告中如实列出

#### Scenario: 声明了不存在的指标名

- **WHEN** 某域声明的被守指标名不在报告的指标名集合中
- **THEN** 装载或门禁比对 MUST 报错指出该名，MUST NOT 静默跳过它

#### Scenario: 声明空集被拒

- **WHEN** 某域声明的 `gated_metrics` 为空
- **THEN** MUST 报错，MUST NOT 以「无被守项」通过门禁

#### Scenario: 预约域行为不变

- **WHEN** 在预约域下以 `--gate` 运行
- **THEN** 被守指标仍为 `工具调用-F1` 与 `槽位抽取完整率`，判定结果与本变更前一致，无需重定基线
