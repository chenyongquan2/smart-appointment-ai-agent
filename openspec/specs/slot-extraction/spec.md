# slot-extraction Specification

## Purpose

通过 Pydantic v2 schema + 结构化输出抽取预约槽位，覆盖现有全部字段并带类型/枚举约束，标准化时间字段，消除裸 JSON prompt + `json.loads` 的脆弱解析，并在抽取失败时返回语义安全的默认槽位。

## Requirements

### Requirement: 预约槽位结构化抽取

系统 SHALL 通过 Pydantic v2 schema（`AppointmentSlots`）+ 结构化输出抽取预约槽位，覆盖现有全部字段：`gender`、`start_time`、`duration`、`project`、`preference`、`technician_name`、`confirmation`、`info_complete`、`unrelated`、`missing_info`。字段 MUST 带类型/枚举约束（如 `info_complete`/`unrelated` 为布尔、`missing_info` 为字符串列表），禁止依赖裸 JSON prompt + `json.loads` 的脆弱解析。

#### Scenario: 完整预约信息被抽取为结构化槽位
- **WHEN** 用户输入"预约张伟技师明天上午10点按摩2小时"
- **THEN** 系统返回 `AppointmentSlots`，其中 `technician_name="张伟"`、`start_time` 为标准格式 `YYYY-MM-DD HH:MM`、`project="按摩"`、`duration="120分钟"`，且 `info_complete=true`

#### Scenario: 缺槽位时标注 missing_info
- **WHEN** 用户输入缺少必需信息（如只说"我要预约"）
- **THEN** `info_complete=false` 且 `missing_info` 列出缺失的关键字段

#### Scenario: 确认回复不被误判为无关
- **WHEN** 用户对技师推荐回复"好"/"可以"/"不要"等简短确认
- **THEN** `confirmation` 捕获该回复，且 `unrelated=false`

### Requirement: 时间字段标准化

`start_time` SHALL 标准化为 `YYYY-MM-DD HH:MM` 格式，相对时间（今天/明天/下午3点）依据当前北京时间换算；无时间信息时取约定的未知占位。该换算规则的语义 MUST 在 schema 字段说明中保留。

#### Scenario: 相对时间被换算为绝对时间
- **WHEN** 用户说"今天下午3点"
- **THEN** `start_time` 输出为当前日期的 `15:00`（标准格式）

### Requirement: 抽取失败安全降级

当结构化抽取本身失败（LLM 调用异常）时，系统 SHALL 返回一个语义安全的默认 `AppointmentSlots`（`info_complete=false`），并记录结构化错误日志，不得让异常使请求崩溃。移除原先依赖 `json.loads` 解析失败才触发的兜底 dict。

#### Scenario: 抽取调用异常
- **WHEN** 抽取过程中 LLM 调用抛出异常
- **THEN** 系统返回 `info_complete=false` 的默认槽位并记录日志，不抛出异常
