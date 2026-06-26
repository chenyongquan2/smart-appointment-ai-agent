## ADDED Requirements

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

## MODIFIED Requirements

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
