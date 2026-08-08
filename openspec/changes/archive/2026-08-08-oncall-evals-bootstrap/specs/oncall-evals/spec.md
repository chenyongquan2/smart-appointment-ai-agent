## ADDED Requirements

### Requirement: 值守域评估用例集与标签口径

值守域 SHALL 在 `domains/oncall/evals/cases.jsonl` 提供一套行为级评估用例集，格式复用既有 jsonl 约定（`//` 注释行与空行跳过、`input` 与 `turns` 恰好其一、`split` 缺省为 `dev`）。

用例的 `expected_intent` SHALL 取自值守域自行声明的 **5 类标签**之一：

| 标签 | 含义 |
|---|---|
| `log_triage` | 查日志排障（含 traceId / 报错片段 / 告警时刻下钻） |
| `code_lookup` | 定位与只读检索服务源码 |
| `docs_lookup` | 查 MT4/MT5 平台文档与返回码 |
| `reference_lookup` | 加载排查资料（服务档案 / 各类错误码表） |
| `other` | 与值守排障无关的输入 |

该标签为**数据集构成元数据**（覆盖约束、按类分项分析、切分规则），SHALL NOT 被理解为对任何分类器组件的依赖，也 SHALL NOT 与预约域的 5 类标签混用或比较。

规模：**dev 子集** SHALL 不少于 30 条且每一类标签不少于 5 条；**held-out 子集** SHALL 不少于 10 条并至少覆盖 3 类标签，其中出现的 **traceId / 错误码 / 源码路径 / 检索词** SHALL NOT 与 dev 子集重复。

服务名**不在**不重复之列：`repos/registry.json` 只登记 `ocs4` / `ocs5` / `mttools` 三个服务，要求不重复等于逼 held-out 用不存在的服务名——那测的是幻觉不是泛化。

#### Scenario: 标签取值合法

- **WHEN** 加载 `domains/oncall/evals/cases.jsonl` 中任一非注释用例
- **THEN** 其 `expected_intent` 必须是值守域声明的 5 类标签之一，否则运行器报错并指出行号

#### Scenario: dev 子集规模与每类下限

- **WHEN** 统计 dev 子集的用例数与按标签分布
- **THEN** dev 子集总量不少于 30 条，且每一类标签不少于 5 条

#### Scenario: held-out 子集规模与不重叠

- **WHEN** 统计 held-out 子集
- **THEN** 总量不少于 10 条、至少覆盖 3 类标签，且其 traceId / 错误码 / 源码路径 / 检索词与 dev 子集无重复（服务名不在此列——全项目仅三个）

### Requirement: 用例覆盖六工具及跨工具组合

用例集 SHALL 覆盖值守域全部六个工具各自被单独触发的场景（`vlog_query`、`load_reference`、`locate_service_code`、`code_search`、`read_source`、`mt_docs_search`），每个工具 SHALL 至少有 3 条以它为唯一期望工具的用例。

用例集 SHALL 另含**跨工具组合**用例，至少覆盖以下三条真实排查链路：

1. 定位服务源码 → 只读检索 → 读取命中处（`locate_service_code` → `code_search` → `read_source`）；
2. 服务/主体/分区元信息 → 按档案定位后查日志（`load_reference` → `vlog_query`）；
3. 错误码分诊 → 平台文档兜底（`load_reference` → `mt_docs_search`，仅当本地速查表未覆盖）。

组合用例的 `expected_tools` 口径为**整段对话累计**，与既有单轮/多轮口径一致。

**「查日志 → 看源码」这条链路 MUST NOT 作为单轮组合用例出现**：值守域系统提示明确要求
「下钻到需要看源码才能定位时，给出日志层结论 + 线索，**本轮不做源码分析**」。标注这条
单轮链路等于让用例期望一个系统提示刻意抑制的行为，压低的是指标而非模型能力。该链路
天然是多轮（先日志、用户再追问源码），随多轮用例一并留作后续切片。

#### Scenario: 每个工具有独立锚点用例

- **WHEN** 按 `expected_tools` 统计用例集
- **THEN** 六个工具各自至少有 3 条「唯一期望工具为它」的用例

#### Scenario: 覆盖三条跨工具链路

- **WHEN** 检视用例集中 `expected_tools` 长度大于 1 的用例
- **THEN** 上述三条链路每条至少有一条对应用例

### Requirement: 值守域门禁守工具 F1 与参数级 F1

值守域的门禁指标集 SHALL 为 `{工具调用-F1, 工具调用-参数级F1}`，`槽位抽取完整率` 对本域 SHALL 按设计标 N/A 且 MUST NOT 进入门禁。

该取舍的依据 SHALL 记录在案：值守域工具的判别性入参（`env` / `platform` / `service` / `load_reference.name`）几乎全为必填项或枚举，在「存在性」口径下只要工具被调用即恒命中，`槽位抽取完整率` 会退化为 `工具调用-F1` 的影子、不提供独立信号；而这些入参取值为枚举或短字面量，正是**精确值比对**成立的前提——故本域改用参数级 F1 作为第二道门禁。

用例 SHALL 通过 `expected_tool_args` 标注可确定性校验的稳定键；**带 schema 默认值的入参**（`window` / `limit` / `glob` / `sync` / `context_lines` / `start_line` / `line_count`）MUST NOT 被标注为期望参数——默认值恒存在会使指标虚高。自由文本入参（`term` / `pattern` / `query` / `logsql`）MUST NOT 被标注为期望参数——其语义等价形态过多，精确比对会恒 miss。

#### Scenario: 门禁实守两项

- **WHEN** 在 `AGENT_DOMAIN=oncall` 下以 `uv run python evals/run_evals.py --gate` 运行且 API key 可用
- **THEN** 门禁报告如实标注被守指标为 `工具调用-F1` 与 `工具调用-参数级F1`，`槽位抽取完整率` 不出现在被守项中

#### Scenario: 默认值入参不进期望标注

- **WHEN** 检视用例集中任一 `expected_tool_args`
- **THEN** 其中不含 `window` / `limit` / `glob` / `sync` / `context_lines` / `start_line` / `line_count` 任一带 schema 默认值的键

### Requirement: 明确不覆盖的指标层与诚实标注

本用例集 SHALL 明确**不覆盖** `回复质量通过率` 与 `任务成功率` 两层，且 SHALL 在 `evals/README.md` 如实标注该边界与理由，MUST NOT 通过标注 `expected_outcome` 或启用未校准 judge 制造出这两项的分母。

理由 SHALL 记录：值守域六工具全为**只读检索型**，不存在预约域 `create_appointment` 那样的事务终态可判「办成没办成」；且回复正确与否依赖代码仓、MT 文档库、日志数据等**真实语料**，语料漂移会使同一条用例的正确答案随时间改变，离线判定不成立。

#### Scenario: 用例不标 expected_outcome

- **WHEN** 检视 `domains/oncall/evals/cases.jsonl` 全部用例
- **THEN** 无任一用例标注 `expected_outcome`，`任务成功率` 在报告中标 N/A 并附「本域不覆盖」说明

#### Scenario: README 标注覆盖边界

- **WHEN** 阅读 `evals/README.md` 关于值守域的章节
- **THEN** 其中明示回复质量与任务成功率两层当前不覆盖及其理由，不以任何形式暗示已覆盖

### Requirement: 用例触发的非确定性靠数据集冗余吸收

单条用例能否触发期望工具 SHALL 被视为**强非确定行为**（预约域实测同一最齐全输入跨跑次触发率约 0.27），本用例集 SHALL NOT 通过反复改写某一条用例来追求「恒触发」。

稳定性 SHALL 靠**数据集冗余**取得：每个工具的锚点用例（不少于 3 条）彼此独立，使「某次跑中某工具的全部锚点均未触发」的概率足够低。报告 SHALL 如实给出当次实守项数；当某次跑因非确定性致某被守指标整体 N/A 时，SHALL 按既有 skipped 语义处理，MUST NOT 表述为「绝对永不回落」。

#### Scenario: 锚点冗余而非单条确定性

- **WHEN** 检视任一工具的锚点用例
- **THEN** 该工具有不少于 3 条彼此独立的锚点用例，且无任何用例的措辞是为「保证恒触发」而反复调校的产物

#### Scenario: 罕见全未触发时诚实回落

- **WHEN** 某次跑因 LLM 非确定性致某被守指标的全部相关用例均未触发工具
- **THEN** 该指标按 skipped 语义标「无法比对」，报告如实给出当次实守项数，不据此判失败也不夸大

### Requirement: 基线由本域用例集独立标定且不与他域比较

`domains/oncall/evals/baseline.json` SHALL 在本用例集上以 `--samples 3 --update-baseline` 标定。门禁容差 SHALL 依定基线时实测的 95% t-CI 半宽校准，MUST NOT 直接沿用预约域的 `0.30`。

本域基线数字与预约域基线数字 SHALL NOT 被并列比较或互相当作目标——两域工具名与任务形态均不同，不可比。

`cases.jsonl` 一经变更（增删改用例），基线 MUST 重新标定，旧基线与新用例集的跑分为 apples-to-oranges。

#### Scenario: 定基线时环境须干净

- **WHEN** 标定基线的跑次中出现 `APIConnectionError` 或网关 5xx 致大批用例记 N/A
- **THEN** MUST NOT 据此落盘基线或调大容差，应修复环境后重跑

#### Scenario: 用例集变更后重定基线

- **WHEN** `domains/oncall/evals/cases.jsonl` 发生增删改
- **THEN** 基线重新标定后方可用于门禁比对
