## MODIFIED Requirements

### Requirement: 评估用例集对齐真实意图口径

评估集 `evals/cases.jsonl` SHALL 以 `输入 → 期望意图` 为用例,且 `expected_intent` MUST 取自真实分类器的 5 类口径之一:`appointment`、`query`、`pay`、`statistics`、`other`。用例集 SHALL 覆盖全部 5 类,并包含边界场景(多槽位、缺槽位追问、改约、与服务无关的输入),总量 SHALL 不少于 18 条。

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

#### Scenario: 注释与空行被跳过

- **WHEN** 文件含 `//` 开头的注释行或空行
- **THEN** 运行器加载时跳过它们,不计入用例

#### Scenario: 多轮用例以 turns 列表表达

- **WHEN** 一条用例提供 `turns`(字符串列表)而非 `input`
- **THEN** 运行器 SHALL 加载该用例并按多轮路径评估,其 `expected_intent` 校验与单轮用例一致

#### Scenario: input 与 turns 互斥

- **WHEN** 一条用例同时提供了 `input` 与 `turns`(或两者皆缺)
- **THEN** 运行器 SHALL 报错并指出行号,MUST NOT 静默猜测

## ADDED Requirements

### Requirement: 多轮对话用例的端到端轨迹评估

评估运行器 `evals/run_evals.py` SHALL 对多轮(`turns`)用例真跑生产路径的 `AgentLoop`,**按轮逐次驱动**并在轮次之间维持对话历史,使评估覆盖「跨轮维持状态、追问后补全槽位、把多轮信息汇总为一次正确工具链」这一单轮覆盖不到的轨迹场景。该多轮采集 SHALL 复用单轮已有的「每条用例一个独立 `Tracer` + `InMemoryExporter` 沙盒、主 Agent → `delegate` → 子 Agent、tracer 透传子 Agent」机制(见本能力既有「真跑端到端 AgentLoop」需求),仅在其上增加按轮驱动的外层循环。

按轮驱动 SHALL 满足:

- **历史累积**:对 `turns` 中第 i 轮,运行器 SHALL 调用 `loop.run(turn_i, history=history)`,其中 `history` 为前 i-1 轮的「用户话语 + agent 最终回复」消息序列;每轮跑完后 SHALL 把本轮用户话语与 agent 最终回复追加进 `history`。该口径 SHALL 与生产 `chat_handler` 的「最近 N 轮窗口仅含 user/assistant 对」一致——轮间不回灌中间工具消息。
- **跨轮采集**:运行器 SHALL 在**同一个 exporter 沙盒**内跑完所有轮次,再从该沙盒的全部 span(含各轮、各子 Agent 的 root span)还原**跨所有轮次**的有序工具序列,填入 `EvalResult.actual_tools`;`actual_slots` 据此跨轮还原(沿用既有「跨工具合并 / last-write-wins / 哨兵剔除」规则)。采集 MUST NOT 仅取末轮或仅按单一 `trace_id` 过滤。
- **最终回复**:多轮用例喂 LLM-judge 的回复 SHALL 取**末轮**的 agent 最终回复(剥离 `[REPLY]` 前缀)。
- **意图判定**:多轮用例的意图分类 SHALL 对 **首轮**话语跑 `classify_task`,与 `expected_intent` 比对;意图准确率口径不因多轮而改变,且 MUST NOT 因引入多轮而重构单轮分类器。

多轮采集 SHALL 实现为可注入 LLM 的形式(可用脚本化 fake LLM 离线确定性单测),与单轮采集函数共享既有的沙盒构造与工具序列还原逻辑,MUST NOT 复制一份独立的工具采集实现。单轮用例的既有评估行为 SHALL 完全不变(向后兼容)。

#### Scenario: 多轮用例按轮累积历史驱动

- **WHEN** 运行器评估一条含 `turns=[t1, t2]` 的用例
- **THEN** 运行器先以空 `history` 跑 `loop.run(t1)`,再以含 `[Human(t1), AI(reply1)]` 的 `history` 跑 `loop.run(t2)`,两轮共用同一 exporter 沙盒

#### Scenario: 跨所有轮次还原工具序列与槽位

- **WHEN** 多轮用例的工具调用分散在不同轮次(如首轮 `find_technician`、末轮 `create_appointment`)
- **THEN** `actual_tools` SHALL 包含跨所有轮次按时序还原的有序工具序列,`actual_slots` SHALL 跨轮合并;MUST NOT 只反映单一轮次

#### Scenario: 多轮意图对首轮判定

- **WHEN** 多轮用例的首轮为开场预约请求、后续轮为补全信息
- **THEN** 意图分类对首轮话语跑 `classify_task` 并与 `expected_intent` 比对

#### Scenario: 单轮行为向后兼容

- **WHEN** 运行器评估一条既有单轮 `input` 用例
- **THEN** 其分类、工具/槽位采集、judge 与延迟口径 SHALL 与本变更前完全一致

#### Scenario: 多轮采集可离线确定性单测

- **WHEN** 用脚本化 fake LLM 注入多轮采集函数并提供固定的逐轮工具调用脚本
- **THEN** 还原出的跨轮工具序列与槽位 SHALL 确定可复现,无需触网
