# eval-harness 规格增量

## REMOVED Requirements

### Requirement: 意图分类准确率基线
**Reason**: 该指标经真调旧分类器（`TaskClassifier.classify_task`）算准确率，而该组件已退出主服务链路——指标度量的是不服务用户的组件，门禁守假目标；harness 架构下意图理解由工具选择体现，已被工具调用指标（name 级 F1 等）覆盖，意图指标是同一信号的冗余重算。
**Migration**: 门禁改守 2 项（见本文件对「基线持久化与回归门禁」的修订）并重定基线；`expected_intent` 标签保留为数据集构成元数据（覆盖/下限规则不变）；意图路由质量此后看工具调用指标。

## MODIFIED Requirements

### Requirement: 评估用例集对齐真实意图口径

评估集 `evals/cases.jsonl` SHALL 以 `输入 → 期望意图` 为用例,且 `expected_intent` MUST 取自数据集意图标签口径的 5 类之一:`appointment`、`query`、`pay`、`statistics`、`other`。该标签为**数据集构成元数据**（用于覆盖约束、按类分项分析与 dev/held-out 切分规则），SHALL NOT 被理解为对某个分类器组件的依赖。用例集 SHALL 覆盖全部 5 类,并包含边界场景(多槽位、缺槽位追问、改约、与服务无关的输入)。

用例集 SHALL 划分为 **dev** 与 **held-out** 两个子集(集归属规则见「用例集 dev / held-out 切分」需求)。**dev 子集**的总量 SHALL 不少于 40 条,且每一类意图在 dev 子集中 SHALL 不少于 5 条(使按类目分项指标具备最低统计意义);**held-out 子集**总量 SHALL 不少于 10 条并至少覆盖 3 类意图。全集(dev + held-out)总量 SHALL 不少于 18 条(向后兼容既有下限)。

用例的「输入」SHALL 支持两种形态,二者向后兼容:

- **单轮**:`input` 为单条用户话语字符串(既有形态,不变)。
- **多轮**:`turns` 为有序的用户话语字符串列表(每个元素是一轮用户输入)。一条用例 SHALL 提供 `input` 与 `turns` 之一;同时提供时 MUST 报错指出行号。单轮 `input` 在语义上等价于单元素 `turns`。

无论单轮还是多轮,`expected_intent` MUST 取自上述 5 类之一;多轮用例的 `expected_tools` / `expected_slots`(若标注)的口径为**整段对话累计**——即期望工具序列/期望槽位键集为跨所有轮次合并后的集合,与既有单轮口径在「单元素 turns」上自然一致。

#### Scenario: 用例意图取值合法

- **WHEN** 加载 `cases.jsonl` 中任一非注释用例
- **THEN** 其 `expected_intent` 必须是 `{appointment, query, pay, statistics, other}` 之一,否则运行器报错并指出行号

#### Scenario: 五类全覆盖

- **WHEN** 统计用例集的 `expected_intent` 分布
- **THEN** 5 个类目每个至少出现一次

#### Scenario: dev 子集规模与每类下限

- **WHEN** 统计 dev 子集的用例数与按类目分布
- **THEN** dev 子集总量不少于 40 条,且每一类意图在 dev 子集中不少于 5 条

#### Scenario: held-out 子集规模与覆盖

- **WHEN** 统计 held-out 子集的用例数与意图覆盖
- **THEN** held-out 子集总量不少于 10 条并至少覆盖 3 类意图

#### Scenario: 注释与空行被跳过

- **WHEN** 文件含 `//` 开头的注释行或空行
- **THEN** 运行器加载时跳过它们,不计入用例

#### Scenario: 多轮用例以 turns 列表表达

- **WHEN** 一条用例提供 `turns`(字符串列表)而非 `input`
- **THEN** 运行器 SHALL 加载该用例并按多轮路径评估,其 `expected_intent` 校验与单轮用例一致

#### Scenario: input 与 turns 互斥

- **WHEN** 一条用例同时提供了 `input` 与 `turns`(或两者皆缺)
- **THEN** 运行器 SHALL 报错并指出行号,MUST NOT 静默猜测

### Requirement: 工具调用为前瞻注解

用例 MAY 携带 `expected_tools`（有序工具名列表）。自本能力起，评估运行器 SHALL 在用例提供 `expected_tools` 且本次捕获到 `actual_tools` 时，按**分档**计算工具调用质量并纳入多指标报告；当用例不含 `expected_tools` 或本次未捕获 `actual_tools` 时，相应档对该用例记为 N/A 而非计入对错。

分档 SHALL 至少包含：

- **召回率 / 精确率 / F1（name 级、按用例宏平均）**：以工具名为单位的部分给分——`recall = |命中∩期望|/|期望|`、`precision = |命中∩期望|/|实际|`、`F1` 为二者调和平均；跨用例宏平均（每条等权）。
- **参数级 F1**：仅对含 `expected_tool_args` 的用例计入（否则该用例该档 N/A）。`expected_tool_args` 为 `{工具名: {键: 值}}`，比对时 SHALL **只比用例标注的键**（actual 多出的键忽略），值做归一化后精确相等。相对时间与自由文本等语义型参数 SHALL NOT 要求纳入（语义等价不在本能力范围）。
- **序列正确率（按用例宏平均）**：`expected_tools` 作为有序**子序列**匹配 `actual_tools`（按全局顺序拍平）即算该用例序列正确；SHALL 容忍 actual 多调/重复工具。
- **完全匹配率（对照）**：保留「实际工具名集合 == 期望集合」的全有或全无判定作最严对照。

每一档 MUST 在无可评估样本时显式标 N/A 并注明原因，MUST NOT 伪造分母或静默跳过。

#### Scenario: 部分命中给部分分

- **WHEN** 某用例 `expected_tools=[A,B,C]` 而实际只调到 `A`
- **THEN** 召回率档对该用例记 1/3（而非完全匹配率档的 0），F1 据召回/精确算出

#### Scenario: 参数级只比标注的键

- **WHEN** 某用例对工具 `find_technician` 标注 `expected_tool_args={"gender":"male"}`，实际调用为 `find_technician(gender="male", project="推拿")`
- **THEN** 参数级档判该工具参数匹配（只比 `gender`，actual 多出的 `project` 不影响）

#### Scenario: 未标 expected_tool_args 的用例参数级记 N/A

- **WHEN** 某用例含 `expected_tools` 但不含 `expected_tool_args`
- **THEN** 参数级 F1 对该用例记 N/A，不计入对错、不伪造分母

#### Scenario: 序列子序列匹配容忍多调

- **WHEN** `expected_tools=[A,C]`，实际有序为 `[A,B,C]`
- **THEN** 序列正确率档判该用例序列正确（A 在 C 前，B 是多调被容忍）

#### Scenario: 序列逆序判错

- **WHEN** `expected_tools=[A,B]`，实际有序为 `[B,A]`
- **THEN** 序列正确率档判该用例序列错误

### Requirement: 多指标评估报告

评估运行器 `evals/run_evals.py` SHALL 产出多指标报告，至少包含：工具调用正确率、槽位抽取完整率、端到端延迟。端到端延迟 SHALL 以**端到端真跑**（驱动 `AgentLoop` 至最终回复）的每条用例耗时计时并汇总，MUST NOT 以任何单一组件的调用耗时冒充端到端口径。对缺少对应期望字段的用例，相应指标 MUST 显式记为 N/A 并在报告中注明，MUST NOT 静默跳过或伪造分母。报告 SHALL 沿用既有约定：通过用例不逐条打印（成功静默），仅详列判错/异常用例。

#### Scenario: 产出多指标总览

- **WHEN** 在 API key 可用时运行 `uv run python evals/run_evals.py`
- **THEN** 报告输出工具调用正确率、槽位抽取完整率与端到端延迟的总览，并仅详列判错用例

#### Scenario: 延迟为端到端真跑口径

- **WHEN** 报告输出端到端延迟
- **THEN** 其计时覆盖该用例端到端真跑全程（多轮用例为跨轮累计），报告注明口径

#### Scenario: 缺期望字段的指标显式标 N/A

- **WHEN** 部分用例缺少 `expected_slots` 或 `expected_tools`
- **THEN** 报告对这些用例的相应指标标注 N/A 并说明，不把缺失当作通过或失败

#### Scenario: 缺少 API key 时优雅降级

- **WHEN** 运行时检测不到可用模型/API key
- **THEN** 运行器打印清晰提示并以非零退出码结束，不抛出未捕获异常崩溃

### Requirement: 基线持久化与回归门禁

评估系统 SHALL 支持把一次跑分结果持久化为**基线**，并在门禁模式下将当前跑分与基线比对、对**精选正确性子集**的回归非零退出，使评估从「人工跑人工看」升级为「自动拦不达标」。

**基线写入**：运行器 SHALL 经 `--update-baseline` 把本次跑分落盘为基线文件（默认 `evals/baseline.json`，可经 `--baseline <path>` 覆盖）。基线 SHALL 记录**全部非 N/A** 指标的值与「是否延迟型」标志（完整快照，供历史与参照），以及元信息（用例数、采样次数、schema 版本）；N/A 指标 MUST NOT 写入基线（不伪造可比项）。基线为人类可读 JSON、可进 git。

**门禁守的指标子集**：门禁 SHALL 只对一个**显式常量**集合 `GATED_METRICS` 判回归，本能力定为 `{工具调用-F1, 槽位抽取完整率}`（均为比率型）。工具调用其余子指标（召回/精确/参数级 F1/序列/完全匹配）、`端到端延迟`、`回复质量通过率` SHALL **不**纳入门禁——延迟环境相关易抖、回复质量来自未校准 judge 不可当真值——它们仍照常打印但 MUST NOT 触发非零退出。

**门禁比对**：运行器 SHALL 经 `--gate` 开启门禁——跑完后对 `GATED_METRICS` 逐项与基线比对，比率型回归判定为 `当前 < 基线 − 容差`。容差经 `--tolerance T` 配置，用于吸收 LLM 的 run-to-run 非确定性抖动；其默认值 SHALL 经基线生成时实测的 95% t-CI 半宽校准以覆盖**全部**被守指标的观测半宽，MUST NOT 是无凭据的魔数。重定基线时 SHALL 复核；实测半宽超出当前容差时 SHALL 按实测上调并记录依据，MUST NOT 沉默沿用旧值。本能力重定实测（41 条 dev × 3，干净跑）：工具 F1 ±5.7pp、槽位抽取完整率 ±28.7pp，故默认容差自 `0.20` 上调为 **`0.30`**（依据与代价见 README）。任一被守指标判回归时，运行器 SHALL 以**退出码 `3`** 结束；无回归则维持既有 `0`。退出码 `3` MUST 区别于既有的 `1`（文件缺失/缺基线）与 `2`（用例非法/无 key 降级）。比对纯函数 MAY 兼容延迟型方向（`当前 > 基线 + 容差`）以备将来，但本能力的门禁集不含延迟指标。

**诚实的比对语义**：被守指标在基线有、但当前为 N/A（或当前有、基线无）时 SHALL 标为「无法比对（skipped）」，MUST NOT 据此判失败或判通过。`槽位抽取完整率` 在 `actual_slots` 接线、且有用例标注 `expected_slots` 后 SHALL 产出真值并参与门禁——其前置（采集还原规则、用例标注口径）由本能力另列的两条需求约束；当某次跑因全部相关用例真跑失败而该指标为 N/A 时，仍按上述 skipped 语义处理。报告 SHALL 如实标注门禁**当前实守**的指标数（本能力为 2 项：工具调用-F1、槽位抽取完整率），MUST NOT 把恒跳过或实际未守的指标呈现为「已守住」。非门禁集中、基线有记录的指标 SHALL 仅作信息提示，不参与 pass/fail。

**纯函数与解耦**：基线序列化（报告/聚合 ↔ 基线 dict）与门禁裁决 SHALL 实现为纯函数（吃当前报告 + 基线 dict + 容差 → 逐指标裁决与整体 pass/fail，不触网、不读写文件），与运行器的 IO（读写 JSON、设置退出码）解耦，可离线确定性单测。

**向后兼容与互斥**：不带 `--gate` 也不带 `--update-baseline` 时，运行器行为 SHALL 与既有完全一致（打印报告、退出 0）。门禁与基线写入均为显式 opt-in，且 `--gate` 与 `--update-baseline` SHALL 互斥（同时给出 → 提示并以退出码 `2` 结束）。

**与采样兼容**：基线 SHALL 可由 `--samples N` 的聚合均值生成；门禁 SHALL 同时适用于单次跑与 `--samples N>1`（后者用各指标的 `mean` 作当前值）。

#### Scenario: 写入基线记全部非 N/A 指标

- **WHEN** 在 API key 可用时以 `--update-baseline` 运行，且某指标本次为 N/A
- **THEN** 基线 JSON 落盘，含本次所有非 N/A 指标的值与元信息，且该 N/A 指标不出现在基线中

#### Scenario: 被守指标回归触发非零退出

- **WHEN** 以 `--gate` 运行，`GATED_METRICS` 中某指标当前值低于「基线 − 容差」
- **THEN** 运行器报告该指标回归（基线 / 当前 / 差值），并以退出码 `3` 结束

#### Scenario: 非门禁指标回归不阻断

- **WHEN** 以 `--gate` 运行，`端到端延迟` 或 `回复质量通过率` 较基线变差，但 `GATED_METRICS` 无回归
- **THEN** 运行器仅信息性打印其变化，不触发退出码 `3`，以退出码 `0` 结束

#### Scenario: 容差内的抖动不算回归

- **WHEN** 以 `--gate` 运行，某被守指标当前值较基线下降但幅度不超过容差
- **THEN** 运行器不判该指标回归，且（在无其它回归时）以退出码 `0` 结束

#### Scenario: 槽位抽取完整率参与门禁

- **WHEN** `actual_slots` 已接线、用例已标 `expected_slots`，以 `--gate` 运行且槽位完整率较基线回归超过容差
- **THEN** 运行器将 `槽位抽取完整率` 判为回归并以退出码 `3` 结束，报告显示门禁实守 2 项

#### Scenario: 基线有当前 N/A 的被守指标标为无法比对

- **WHEN** 以 `--gate` 运行，`槽位抽取完整率` 在基线中有值但本次跑为 N/A（如全部相关用例真跑失败）
- **THEN** 运行器将该指标标为「无法比对（skipped）」，不据此判失败也不据此判通过，并如实标注门禁实守的指标数

#### Scenario: 门禁比对为纯函数可离线测

- **WHEN** 给定一份当前报告、一份基线 dict 与容差，调用门禁比对纯函数
- **THEN** 不触网即可断言逐指标裁决（ok/regressed/skipped/new）与整体 pass/fail

#### Scenario: 默认不开门禁向后兼容

- **WHEN** 不带 `--gate` 也不带 `--update-baseline` 运行评估
- **THEN** 行为与既有完全一致：打印报告并以退出码 `0` 结束，不读写基线文件

#### Scenario: gate 与 update-baseline 互斥

- **WHEN** 同时传 `--gate` 与 `--update-baseline`
- **THEN** 运行器打印清晰提示并以退出码 `2` 结束，不读写基线文件

#### Scenario: 门禁模式缺基线文件优雅报错

- **WHEN** 以 `--gate` 运行但基线文件不存在
- **THEN** 运行器打印清晰提示（指引先 `--update-baseline` 建基线）并以非零退出码 `1` 结束，不抛未捕获异常崩溃

### Requirement: 预约类用例策展以稳定触发工具链使槽位完整率非 N/A

为使门禁稳定实守 2 项（工具调用-F1、槽位抽取完整率），评估用例 `evals/cases.jsonl` 中**带 `expected_slots` 的预约（appointment）类用例** SHALL 以**信息齐全的祈使式单轮输入**为主——即在单轮内同时给出足以触发工具链的关键信息（至少含时间与项目，并视用例补全 duration / technician / gender / preference 等），且表达明确的办理/下单意图，使保守的预约子 Agent（[harness/subagents/appointment.py](../../../harness/subagents/appointment.py) 系统提示「信息不足则追问、不臆测下单」）倾向**直接调用工具办理**而非反问澄清，从而让 `actual_slots` 稳定从工具调用 args 还原出真值。

带 `expected_slots` 的此类用例 SHALL 在数量上足够（多条独立用例），使「某次跑中所有相关用例都未触发任何工具」这一导致 `槽位抽取完整率` 整体 N/A 的情形发生概率足够低；在常规门禁跑（含 `--samples N`）下，`槽位抽取完整率` SHALL 稳定产出真值并被门禁实守。

本需求 SHALL NOT 改变 `槽位抽取完整率` 的「存在性口径」（只看期望槽位键是否被抽出、不比精确值），SHALL NOT 改变子 Agent 行为、系统提示或任何 `services/` / `harness/runtime` 业务逻辑——唯一杠杆是用例（数据集）本身。

诚实边界 SHALL 保留：本需求降低而非消除回落概率；当某次跑因 LLM 非确定性致全部相关用例罕见地均未触发工具时，`槽位抽取完整率` 仍按既有 skipped 语义处理、报告如实给出当次实守项数，MUST NOT 把「稳定守 2 项」表述为「绝对永不回落」。

#### Scenario: 信息齐全的祈使式预约用例具有可观触发概率

- **WHEN** 在 API key 可用时对一条信息齐全的祈使式预约用例（精确时间 + 项目 + 点名具体技师等）多次真跑 `AgentLoop`
- **THEN** 该用例在相当比例的跑次中触发领域工具（如 `find_technician` / `check_availability`），`actual_slots` 从工具调用 args 还原出非 None 的槽位 dict 并计入 `槽位抽取完整率`；单条触发为 LLM 非确定行为、不要求恒触发，故策展靠**足量此类用例的冗余**而非任何单条的确定性

#### Scenario: 常规门禁跑稳定实守 2 项

- **WHEN** 以 `uv run python evals/run_evals.py --gate --samples 3` 运行
- **THEN** `槽位抽取完整率` 产出真值（非 N/A），门禁报告如实标注当次实守 2 项（工具调用-F1、槽位抽取完整率）

#### Scenario: 存在性口径与子 Agent 行为不变

- **WHEN** 应用本需求策展用例后检视评估口径与业务代码
- **THEN** `槽位抽取完整率` 仍按存在性口径判定（键存在即命中、不比值），且 `harness/subagents/` 子 Agent 提示与 `services/` 业务逻辑未被改动

#### Scenario: 罕见全未触发时诚实回落

- **WHEN** 某次跑因 LLM 非确定性致全部带 `expected_slots` 的预约用例均未触发任何工具
- **THEN** `槽位抽取完整率` 按既有 skipped 语义标「无法比对」，报告如实给出当次实守项数（回落为 1），不据此判失败也不夸大为「已守 2 项」

### Requirement: 评估运行器真跑端到端 AgentLoop 并采集真实工具调用

评估运行器 `evals/run_evals.py` SHALL 对每条用例真跑生产路径的 `AgentLoop`（主 Agent → `delegate` → 子 Agent），并从 trace 采集该次运行实际触发的工具调用，填入 `EvalResult.actual_tools`，使工具调用正确率从恒 N/A 翻成真实数字。

运行器 SHALL 自行构造一个带真 `Tracer` 与 `InMemoryExporter` 的主 loop（经 `build_default_registry()` + `build_default_subagent_registry()` + `build_delegate_tool()`），MUST NOT 复用生产路径中默认走 `NoopTracer` 的全局 `AgentLoop` 单例。

工具调用采集 SHALL 以「每条用例一个独立 exporter 沙盒」为边界：收集该 exporter 内所有 span（含子 Agent 各自的 root span）的 `tool_call` 事件，按 `(span.start, 事件顺序)` 还原为有序序列。采集 MUST NOT 仅按单一 `trace_id` 过滤（子 Agent 自开 root 会漏采）。

`EvalResult.actual_tools` SHALL 采全为有序的 `{name, args}` 序列（name 与 args 一并保留）。

真跑路径 SHALL 仅在 API key 可用时启用；无 key 时 MUST 沿用既有优雅降级（提示 + 非零退出，不崩）。

#### Scenario: 真跑后工具调用正确率不再恒 N/A

- **WHEN** 在 API key 可用时运行 `uv run python evals/run_evals.py`，且用例含 `expected_tools`
- **THEN** 运行器真跑 `AgentLoop` 并采集到实际工具调用，工具调用正确率给出真实数字而非 N/A

#### Scenario: 采集覆盖子 Agent 内的工具调用

- **WHEN** 某用例触发主 Agent 经 `delegate` 派生子 Agent，由子 Agent 执行领域工具
- **THEN** 采集到的工具序列包含子 Agent 内实际触发的领域工具（如 `find_technician`），而非仅 `delegate`

#### Scenario: 采全比松

- **WHEN** 采集某次运行的实际工具调用
- **THEN** `actual_tools` 保留每次调用的 `name` 与 `args` 且有序，各分档按其口径比对（name 集合 / 参数级 / 序列级）

#### Scenario: 无 key 时不真跑

- **WHEN** 运行时检测不到可用模型/API key
- **THEN** 运行器不驱动 `AgentLoop`，沿用既有优雅降级路径（打印用例清单/提示并非零退出）

### Requirement: 用例集 dev / held-out 切分

评估集的每条用例 SHALL 携带一个「集归属」标记以区分 **dev** 与 **held-out**;未显式标记的用例 SHALL 默认归入 **dev**(向后兼容——既有用例无需改动即属 dev)。切分的目的是防过拟合:held-out 子集**用作过拟合体检的留出集**,MUST NOT 被用于任何 prompt / 用例 / 阈值的调优,也 MUST NOT 参与门禁基线的生成与回归判定。

运行器 `evals/run_evals.py` SHALL 满足:

- **默认只评 dev**:不带 held-out 开关时,运行器 SHALL 只加载并评估 dev 子集;工具/槽位等各项指标、`--update-baseline`、`--gate` 的口径 SHALL 全部基于 dev 子集,与本变更前的默认行为等价(held-out 用例被排除,不影响任何既有数字与门禁)。
- **按需评 held-out**:提供显式开关(如 `--include-heldout` 或 `--heldout-only`)时,运行器 SHALL 评估 held-out 子集并**单独分集呈现**其指标,MUST NOT 把 held-out 结果混入 dev 基线或触发门禁的非零退出。
- **分集透明**:报告 SHALL 标明各指标是在 dev 还是 held-out 子集上计算、以及各子集用例数,MUST NOT 让读者误以为 held-out 参与了门禁。

集归属的校验 SHALL 与既有加载校验一致(非法标记值报行号退出),集归属标记 SHALL 进 git、可追溯。

#### Scenario: 默认运行只评 dev 且门禁基于 dev

- **WHEN** 不带 held-out 开关运行 `uv run python evals/run_evals.py`(或 `--gate` / `--update-baseline`)
- **THEN** 运行器只加载 dev 子集,所有指标、基线与门禁判定均基于 dev;held-out 用例被排除,不影响任何数字或退出码

#### Scenario: 显式请求时按需评 held-out 并分集呈现

- **WHEN** 带 held-out 开关运行运行器
- **THEN** held-out 子集被评估、其指标单独分集呈现,MUST NOT 混入 dev 基线,MUST NOT 触发门禁非零退出

#### Scenario: 未标记用例默认归 dev(向后兼容)

- **WHEN** 加载一条未携带集归属标记的既有用例
- **THEN** 该用例归入 dev 子集,评估行为与本变更前完全一致

#### Scenario: 非法集归属标记报错

- **WHEN** 一条用例的集归属标记不是 `{dev, held-out}` 之一
- **THEN** 运行器报错并指出行号,MUST NOT 静默归类

#### Scenario: held-out 不参与调优与门禁

- **WHEN** 生成门禁基线(`--update-baseline`)或执行回归判定(`--gate`)
- **THEN** 只有 dev 子集参与;held-out 子集 MUST NOT 影响基线内容或回归结论

### Requirement: 多轮对话用例的端到端轨迹评估

评估运行器 `evals/run_evals.py` SHALL 对多轮(`turns`)用例真跑生产路径的 `AgentLoop`,**按轮逐次驱动**并在轮次之间维持对话历史,使评估覆盖「跨轮维持状态、追问后补全槽位、把多轮信息汇总为一次正确工具链」这一单轮覆盖不到的轨迹场景。该多轮采集 SHALL 复用单轮已有的「每条用例一个独立 `Tracer` + `InMemoryExporter` 沙盒、主 Agent → `delegate` → 子 Agent、tracer 透传子 Agent」机制(见本能力既有「真跑端到端 AgentLoop」需求),仅在其上增加按轮驱动的外层循环。

按轮驱动 SHALL 满足:

- **历史累积**:对 `turns` 中第 i 轮,运行器 SHALL 调用 `loop.run(turn_i, history=history)`,其中 `history` 为前 i-1 轮的「用户话语 + agent 最终回复」消息序列;每轮跑完后 SHALL 把本轮用户话语与 agent 最终回复追加进 `history`。该口径 SHALL 与生产 `chat_handler` 的「最近 N 轮窗口仅含 user/assistant 对」一致——轮间不回灌中间工具消息。
- **跨轮采集**:运行器 SHALL 在**同一个 exporter 沙盒**内跑完所有轮次,再从该沙盒的全部 span(含各轮、各子 Agent 的 root span)还原**跨所有轮次**的有序工具序列,填入 `EvalResult.actual_tools`;`actual_slots` 据此跨轮还原(沿用既有「跨工具合并 / last-write-wins / 哨兵剔除」规则)。采集 MUST NOT 仅取末轮或仅按单一 `trace_id` 过滤。
- **最终回复**:多轮用例喂 LLM-judge 的回复 SHALL 取**末轮**的 agent 最终回复(剥离 `[REPLY]` 前缀)。

多轮采集 SHALL 实现为可注入 LLM 的形式(可用脚本化 fake LLM 离线确定性单测),与单轮采集函数共享既有的沙盒构造与工具序列还原逻辑,MUST NOT 复制一份独立的工具采集实现。单轮用例的既有评估行为 SHALL 完全不变(向后兼容)。

#### Scenario: 多轮用例按轮累积历史驱动

- **WHEN** 运行器评估一条含 `turns=[t1, t2]` 的用例
- **THEN** 运行器先以空 `history` 跑 `loop.run(t1)`,再以含 `[Human(t1), AI(reply1)]` 的 `history` 跑 `loop.run(t2)`,两轮共用同一 exporter 沙盒

#### Scenario: 跨所有轮次还原工具序列与槽位

- **WHEN** 多轮用例的工具调用分散在不同轮次(如首轮 `find_technician`、末轮 `create_appointment`)
- **THEN** `actual_tools` SHALL 包含跨所有轮次按时序还原的有序工具序列,`actual_slots` SHALL 跨轮合并;MUST NOT 只反映单一轮次

#### Scenario: 单轮行为向后兼容

- **WHEN** 运行器评估一条既有单轮 `input` 用例
- **THEN** 其工具/槽位采集、judge 与延迟口径 SHALL 与本变更后的单轮约定完全一致

#### Scenario: 多轮采集可离线确定性单测

- **WHEN** 用脚本化 fake LLM 注入多轮采集函数并提供固定的逐轮工具调用脚本
- **THEN** 还原出的跨轮工具序列与槽位 SHALL 确定可复现,无需触网
