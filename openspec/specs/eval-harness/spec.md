# eval-harness Specification

## Purpose
TBD - created by archiving change phase-0-evals-baseline. Update Purpose after archive.
## Requirements
### Requirement: 评估用例集对齐真实意图口径

评估集 `evals/cases.jsonl` SHALL 以 `输入 → 期望意图` 为用例,且 `expected_intent` MUST 取自真实分类器的 5 类口径之一:`appointment`、`query`、`pay`、`statistics`、`other`。用例集 SHALL 覆盖全部 5 类,并包含边界场景(多槽位、缺槽位追问、改约、与服务无关的输入),总量 SHALL 不少于 18 条。

#### Scenario: 用例意图取值合法

- **WHEN** 加载 `cases.jsonl` 中任一非注释用例
- **THEN** 其 `expected_intent` 必须是 `{appointment, query, pay, statistics, other}` 之一,否则运行器报错并指出行号

#### Scenario: 五类全覆盖

- **WHEN** 统计用例集的 `expected_intent` 分布
- **THEN** 5 个类目每个至少出现一次

#### Scenario: 注释与空行被跳过

- **WHEN** 文件含 `//` 开头的注释行或空行
- **THEN** 运行器加载时跳过它们,不计入用例

### Requirement: 意图分类准确率基线

运行器 `evals/run_evals.py` SHALL 经 `config/model_provider` 实例化真实 `TaskClassifier`,对每条用例执行 `classify_task`,将结果与 `expected_intent` 比对,并 SHALL 输出总准确率、按类目分项准确率,以及逐条错误清单(输入 / 期望 / 实际)。通过的用例 SHALL NOT 逐条打印(成功静默)。

#### Scenario: 产出基线

- **WHEN** 在 API key 可用时运行 `uv run python evals/run_evals.py`
- **THEN** 输出形如"意图准确率 X/N (P%)"的总览,并仅详列判错的用例

#### Scenario: 缺少 API key 时优雅降级

- **WHEN** 运行时检测不到可用模型/API key
- **THEN** 运行器打印清晰提示并以非零退出码结束,不抛出未捕获异常崩溃

### Requirement: 工具调用为前瞻注解

用例 MAY 携带 `expected_tools`（有序工具名列表）。自本能力起，评估运行器 SHALL 在用例提供 `expected_tools` 且本次捕获到 `actual_tools` 时，按**分档**计算工具调用质量并纳入多指标报告；当用例不含 `expected_tools` 或本次未捕获 `actual_tools` 时，相应档对该用例记为 N/A 而非计入对错。意图准确率的判定 SHALL NOT 受 `expected_tools` 影响。

分档 SHALL 至少包含：

- **召回率 / 精确率 / F1（name 级、按用例宏平均）**：以工具名为单位的部分给分——`recall = |命中∩期望|/|期望|`、`precision = |命中∩期望|/|实际|`、`F1` 为二者调和平均；跨用例宏平均（每条等权）。
- **参数级 F1**：仅对含 `expected_tool_args` 的用例计入（否则该用例该档 N/A）。`expected_tool_args` 为 `{工具名: {键: 值}}`，比对时 SHALL **只比用例标注的键**（actual 多出的键忽略），值做归一化后精确相等。相对时间与自由文本等语义型参数 SHALL NOT 要求纳入（语义等价不在本能力范围）。
- **序列正确率（按用例宏平均）**：`expected_tools` 作为有序**子序列**匹配 `actual_tools`（按全局顺序拍平）即算该用例序列正确；SHALL 容忍 actual 多调/重复工具。
- **完全匹配率（对照）**：保留「实际工具名集合 == 期望集合」的全有或全无判定作最严对照。

每一档 MUST 在无可评估样本时显式标 N/A 并注明原因，MUST NOT 伪造分母或静默跳过。

#### Scenario: expected_tools 不影响意图准确率

- **WHEN** 计算意图分类准确率
- **THEN** `expected_tools` 与 `expected_tool_args` 被忽略，不参与意图对错判定

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

评估运行器 `evals/run_evals.py` SHALL 在意图准确率之外，产出多指标报告，至少包含：工具调用正确率、槽位抽取完整率、端到端延迟（每条用例计时并汇总）。对缺少对应期望字段的用例，相应指标 MUST 显式记为 N/A 并在报告中注明，MUST NOT 静默跳过或伪造分母。报告 SHALL 沿用既有约定：通过用例不逐条打印（成功静默），仅详列判错/异常用例。

#### Scenario: 产出多指标总览

- **WHEN** 在 API key 可用时运行 `uv run python evals/run_evals.py`
- **THEN** 报告输出意图准确率、工具调用正确率、槽位抽取完整率与端到端延迟的总览，并仅详列判错用例

#### Scenario: 缺期望字段的指标显式标 N/A

- **WHEN** 部分用例缺少 `expected_slots` 或 `expected_tools`
- **THEN** 报告对这些用例的相应指标标注 N/A 并说明，不把缺失当作通过或失败

#### Scenario: 缺少 API key 时优雅降级

- **WHEN** 运行时检测不到可用模型/API key
- **THEN** 运行器打印清晰提示并以非零退出码结束，不抛出未捕获异常崩溃

### Requirement: 评估运行器真跑端到端 AgentLoop 并采集真实工具调用

评估运行器 `evals/run_evals.py` SHALL 在意图分类之外，对每条用例真跑生产路径的 `AgentLoop`（主 Agent → `delegate` → 子 Agent），并从 trace 采集该次运行实际触发的工具调用，填入 `EvalResult.actual_tools`，使工具调用正确率从恒 N/A 翻成真实数字。

运行器 SHALL 自行构造一个带真 `Tracer` 与 `InMemoryExporter` 的主 loop（经 `build_default_registry()` + `build_default_subagent_registry()` + `build_delegate_tool()`），MUST NOT 复用生产路径中默认走 `NoopTracer` 的全局 `AgentLoop` 单例。

工具调用采集 SHALL 以「每条用例一个独立 exporter 沙盒」为边界：收集该 exporter 内所有 span（含子 Agent 各自的 root span）的 `tool_call` 事件，按 `(span.start, 事件顺序)` 还原为有序序列。采集 MUST NOT 仅按单一 `trace_id` 过滤（子 Agent 自开 root 会漏采）。

`EvalResult.actual_tools` SHALL 采全为有序的 `{name, args}` 序列（name 与 args 一并保留）；但本次工具调用正确率指标 SHALL 仍只做工具名集合（`set`）比较，参数级与序列级比对不在本次范围。

真跑路径 SHALL 仅在 API key 可用时启用；无 key 时 MUST 沿用既有优雅降级（提示 + 非零退出，不崩）。

#### Scenario: 真跑后工具调用正确率不再恒 N/A

- **WHEN** 在 API key 可用时运行 `uv run python evals/run_evals.py`，且用例含 `expected_tools`
- **THEN** 运行器真跑 `AgentLoop` 并采集到实际工具调用，工具调用正确率给出真实数字而非 N/A

#### Scenario: 采集覆盖子 Agent 内的工具调用

- **WHEN** 某用例触发主 Agent 经 `delegate` 派生子 Agent，由子 Agent 执行领域工具
- **THEN** 采集到的工具序列包含子 Agent 内实际触发的领域工具（如 `find_technician`），而非仅 `delegate`

#### Scenario: 采全比松

- **WHEN** 采集某次运行的实际工具调用
- **THEN** `actual_tools` 保留每次调用的 `name` 与 `args` 且有序，但工具调用正确率仅按工具名集合比对（不查参数、不校验顺序）

#### Scenario: 无 key 时不真跑

- **WHEN** 运行时检测不到可用模型/API key
- **THEN** 运行器不驱动 `AgentLoop`，沿用既有优雅降级路径（打印用例清单/提示并非零退出）

### Requirement: 多次采样与聚合指标置信区间

评估运行器 SHALL 支持可配的多次采样：经 `--samples N`（默认 `N=1`）控制整套用例的重跑次数。`N=1` 时行为 SHALL 与单次跑完全一致（向后兼容）。`N>1` 时运行器 SHALL 整套用例独立重跑 N 次，并对每个聚合指标跨 N 次跑计算 `mean` 与置信区间。

置信区间 SHALL 用 **t 分布**计算：`mean ± t_(N-1, 0.975) · s/√N`（s 为 N 个 run 级聚合值的样本标准差），把每次整套跑的聚合值当作一个观测。实现 MUST NOT 对小样本用正态(z)近似代替 t。t 临界值 MAY 用硬编码小表（零额外依赖）。

该 CI MUST 在报告中被标注为 **run-to-run（LLM 抖动）** 的不确定性，并 MUST NOT 被声称为涵盖数据集大小的不确定性（后者需更大用例集，不在本能力范围）。

当 N 次跑的聚合值完全相同（`s=0`，如 `temperature=0` 残余抖动可忽略）时，CI 宽度 SHALL 为 0，报告 SHALL 给出点值并标注稳定，MUST NOT 当作错误。

CI 与方差的计算 SHALL 为纯函数（吃一组 per-run 指标值、不触网、可离线确定性单测），与触网的采样循环解耦。

#### Scenario: 默认单次跑向后兼容

- **WHEN** 不传 `--samples`（或 `--samples 1`）运行评估
- **THEN** 行为与既有单次跑完全一致，报告不含 CI 列

#### Scenario: 多次采样产出 mean ± CI

- **WHEN** 以 `--samples 5` 运行，且某聚合指标在 5 次跑中取值不全相同
- **THEN** 报告对该指标给出 `mean ± CI（n=5 次）`，CI 由 t 分布按 `mean ± t_(4,0.975)·s/√5` 算出

#### Scenario: 零方差给零宽 CI

- **WHEN** 某指标在 N 次跑中取值完全相同
- **THEN** 报告给出该指标的点值、CI 宽度为 0 并标注稳定，不报错

#### Scenario: CI 含义被正确标注

- **WHEN** 报告展示置信区间
- **THEN** 标注其为 run-to-run（LLM 抖动）不确定性，且不声称涵盖数据集大小的不确定性

### Requirement: LLM-as-judge 评回复质量（pointwise 二元）

评估 SHALL 提供一个 LLM-as-judge 对 agent 最终回复做**回复质量**裁决。judge SHALL 用结构化输出返回二元裁决 `{pass: bool, reason: str}`，judge MUST 先产出 `reason` 再给 `pass`（先推理后裁决）。judge 调用 SHALL 用 `temperature=0`，且其 LLM SHALL 可注入（便于用 fake judge 离线确定性单测）。

裁决聚合 SHALL 为纯函数：`response_quality` 吃一组裁决产出**质量通过率**（pass 占比）。无任何裁决（未开启 judge 或未捕获回复）时 SHALL 显式标 N/A，MUST NOT 伪造分母。

judge 默认关闭，经 `--judge` 显式开启（judge 为每条用例的额外 LLM 调用）。judge 评的是「回复是否恰当且正确地回应用户请求」的复合判断；RAG 三元组（faithfulness 等）不在本能力范围。

#### Scenario: judge 产出二元裁决并聚合为通过率

- **WHEN** 以 `--judge` 运行，judge 对每条回复返回 `{pass, reason}`
- **THEN** 报告输出回复质量通过率（pass 占比），并对裁决聚合用纯函数计算

#### Scenario: 未开启 judge 时回复质量记 N/A

- **WHEN** 不带 `--judge` 运行
- **THEN** 回复质量指标显式标 N/A，不伪造分母、不计入对错

#### Scenario: judge 调用层可用 fake judge 离线测

- **WHEN** 注入一个脚本化 fake judge LLM 跑 judge 调用层
- **THEN** 不触网即可断言裁决解析与聚合，裁决聚合为纯函数

### Requirement: judge 校准机制与未校准显式标注

评估 SHALL 提供纯函数 `judge_human_agreement(judge_labels, human_labels)`，对二元标注计算 **judge 与人工的一致率与 Cohen's κ**。系统 SHALL 提供一个校准集占位（供人工填真实 pass/fail 标注），且 MUST NOT 伪造人工标注。

在人工校准标注缺失时，回复质量报告 SHALL 显式标注 judge 为「未校准（κ 未测）」，MUST NOT 把未经校准的 judge 结果呈现为可信真值。judge 与 agent 同模型导致的自我偏好风险 SHALL 在文档/报告中作为已知局限说明。

#### Scenario: 算 judge 与人工一致率与 κ

- **WHEN** 给定一组 judge 二元标注与对应的人工二元标注
- **THEN** `judge_human_agreement` 返回一致率与 Cohen's κ（纯函数、可离线断言）

#### Scenario: 缺人工标注时标未校准

- **WHEN** 校准集无人工标注而运行 judge
- **THEN** 报告显式标注 judge「未校准」，不声称其裁决为可信真值

### Requirement: 基线持久化与回归门禁

评估系统 SHALL 支持把一次跑分结果持久化为**基线**，并在门禁模式下将当前跑分与基线比对、对**精选正确性子集**的回归非零退出，使评估从「人工跑人工看」升级为「自动拦不达标」。

**基线写入**：运行器 SHALL 经 `--update-baseline` 把本次跑分落盘为基线文件（默认 `evals/baseline.json`，可经 `--baseline <path>` 覆盖）。基线 SHALL 记录**全部非 N/A** 指标的值与「是否延迟型」标志（完整快照，供历史与参照），以及元信息（用例数、采样次数、schema 版本）；N/A 指标 MUST NOT 写入基线（不伪造可比项）。基线为人类可读 JSON、可进 git。

**门禁守的指标子集**：门禁 SHALL 只对一个**显式常量**集合 `GATED_METRICS` 判回归，本能力定为 `{意图分类准确率, 工具调用-F1, 槽位抽取完整率}`（均为比率型）。工具调用其余子指标（召回/精确/参数级 F1/序列/完全匹配）、`端到端延迟`、`回复质量通过率` SHALL **不**纳入门禁——延迟环境相关易抖、回复质量来自未校准 judge 不可当真值——它们仍照常打印但 MUST NOT 触发非零退出。

**门禁比对**：运行器 SHALL 经 `--gate` 开启门禁——跑完后对 `GATED_METRICS` 逐项与基线比对，比率型回归判定为 `当前 < 基线 − 容差`。容差经 `--tolerance T` 配置，用于吸收 LLM 的 run-to-run 非确定性抖动；其默认值 SHALL 经基线生成时实测的 95% t-CI 半宽校准以覆盖观测抖动（本能力定为 `0.20`，依据见 README），MUST NOT 是无凭据的魔数。任一被守指标判回归时，运行器 SHALL 以**退出码 `3`** 结束；无回归则维持既有 `0`。退出码 `3` MUST 区别于既有的 `1`（文件缺失/缺基线）与 `2`（用例非法/无 key 降级）。比对纯函数 MAY 兼容延迟型方向（`当前 > 基线 + 容差`）以备将来，但本能力的门禁集不含延迟指标。

**诚实的比对语义**：被守指标在基线有、但当前为 N/A（或当前有、基线无）时 SHALL 标为「无法比对（skipped）」，MUST NOT 据此判失败或判通过。`槽位抽取完整率` 在 `actual_slots` 接线、且有用例标注 `expected_slots` 后 SHALL 产出真值并参与门禁——其前置（采集还原规则、用例标注口径）由本能力另列的两条需求约束；当某次跑因全部相关用例真跑失败而该指标为 N/A 时，仍按上述 skipped 语义处理。报告 SHALL 如实标注门禁**当前实守**的指标数（接线后为 3 项：意图分类准确率、工具调用-F1、槽位抽取完整率），MUST NOT 把恒跳过或实际未守的指标呈现为「已守住」，也 MUST NOT 把已接线指标继续标注为「结构性恒 N/A」。非门禁集中、基线有记录的指标 SHALL 仅作信息提示，不参与 pass/fail。

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

#### Scenario: 槽位抽取完整率接线后参与门禁

- **WHEN** `actual_slots` 已接线、用例已标 `expected_slots`，以 `--gate` 运行且槽位完整率较基线回归超过容差
- **THEN** 运行器将 `槽位抽取完整率` 判为回归并以退出码 `3` 结束，报告显示门禁实守 3 项

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

### Requirement: 槽位采集（actual_slots）从工具调用还原

评估运行器 SHALL 从端到端真跑采集到的工具调用序列（`CaptureResult.tool_calls`，每项含 `name` 与 `args`）**还原**出一份扁平的「实际槽位」dict `actual_slots`，键归一到统一的槽位口径 `{start_time, duration, project, preference, gender, technician}`，用作 `槽位抽取完整率` 指标的当前值输入。该还原 SHALL 实现为**纯函数**（吃工具调用列表 → 返回槽位 dict，不触网、不读写文件），可离线确定性单测。

还原规则 SHALL 满足：

- **跨工具合并**：槽位分散在多个工具的 args 中（如 `find_technician.project`、`create_appointment.project`、`check_availability.duration`），还原时 SHALL 把各工具调用中的槽位字段合并进同一份 dict；`technician_name` 归一为槽位键 `technician`。
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

### Requirement: 槽位抽取完整率为存在性口径（非精确值匹配）

`槽位抽取完整率` SHALL 度量「期望槽位中**被抽出**的比例」——即期望槽位的键是否出现在还原出的 `actual_slots` 中（键存在即命中），**MUST NOT** 比对槽位的精确值。哨兵默认值已在 `actual_slots` 还原阶段剔除，故「键存在于 `actual_slots`」即等价于「模型抽到了一个非默认的真实值」。该口径与 `expected_tool_args` 喂的参数级 P/R/F1（比对精确值、按工具拆分）刻意区分：前者度量「抽没抽到」（coverage），后者度量「抽得对不对」（accuracy），两者口径分明、不重叠。

选此口径的依据：当前 agent 抽出的槽位值为自由文本且不规范（如 `gender='男'` 而非 `male`、`start_time` 可能为模型算错的日期），精确值匹配会令指标几乎恒 miss、失去意义；存在性口径绕开值噪声，贴合「完整率/coverage」本义。

#### Scenario: 键存在即命中、不比值

- **WHEN** 某用例 `expected_slots` 含键 `project`，`actual_slots` 含 `project`（无论其值是否等于 `expected_slots` 标注的说明值）
- **THEN** 该 `project` 槽位计为命中

#### Scenario: 键缺失算未命中

- **WHEN** 某用例 `expected_slots` 含键 `gender`，但 `actual_slots` 不含 `gender`（模型未抽出或仅为哨兵默认值被剔除）
- **THEN** 该 `gender` 槽位计为未命中

### Requirement: 用例标注 expected_slots 与 expected_tool_args 区分口径

评估用例 `evals/cases.jsonl` 的预约类用例 SHALL 可标注 `expected_slots`——一份扁平 dict，其**键**为「整轮跨工具应被抽到的槽位键集合」（取自统一槽位口径），用作 `槽位抽取完整率` 的期望分母；其**值仅作人类可读说明、不参与判定**（存在性口径，见上条需求）。`expected_slots` 与既有 `expected_tool_args` SHALL 口径分明、各司其职：`expected_tool_args` 标注**逐工具**的参数稳定键并比对**精确值**（参数级 P/R/F1、按工具拆分）；`expected_slots` 标注**整轮跨工具**应抽到的槽位键集合、只看**存在性**（宏平均完整率、门禁守的那个）。两者 MAY 在键上重叠（如均含 `project`），但 MUST NOT 互相派生而隐藏口径差异；缺 `expected_slots` 的用例其槽位指标按既有约定标 N/A。

#### Scenario: 标注 expected_slots 的用例参与槽位完整率

- **WHEN** 某预约用例标注了 `expected_slots`，且端到端真跑还原出 `actual_slots`（非 None）
- **THEN** 该用例计入 `槽位抽取完整率`（命中数 / 期望槽位数的宏平均，命中按存在性判定），不再标 N/A

#### Scenario: 未标 expected_slots 仍标 N/A

- **WHEN** 用例未标注 `expected_slots`
- **THEN** 该用例的 `槽位抽取完整率` 标 N/A，不计入分母，与既有「多指标报告」约定一致

