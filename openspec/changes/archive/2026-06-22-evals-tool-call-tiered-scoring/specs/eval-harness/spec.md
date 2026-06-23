## MODIFIED Requirements

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
