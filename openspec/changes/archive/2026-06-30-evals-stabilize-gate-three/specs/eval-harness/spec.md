## ADDED Requirements

### Requirement: 预约类用例策展以稳定触发工具链使槽位完整率非 N/A

为使门禁稳定实守 3 项（意图分类准确率、工具调用-F1、槽位抽取完整率），评估用例 `evals/cases.jsonl` 中**带 `expected_slots` 的预约（appointment）类用例** SHALL 以**信息齐全的祈使式单轮输入**为主——即在单轮内同时给出足以触发工具链的关键信息（至少含时间与项目，并视用例补全 duration / technician / gender / preference 等），且表达明确的办理/下单意图，使保守的预约子 Agent（[harness/subagents/appointment.py](../../../../harness/subagents/appointment.py) 系统提示「信息不足则追问、不臆测下单」）倾向**直接调用工具办理**而非反问澄清，从而让 `actual_slots` 稳定从工具调用 args 还原出真值。

带 `expected_slots` 的此类用例 SHALL 在数量上足够（多条独立用例），使「某次跑中所有相关用例都未触发任何工具」这一导致 `槽位抽取完整率` 整体 N/A 的情形发生概率足够低；在常规门禁跑（含 `--samples N`）下，`槽位抽取完整率` SHALL 稳定产出真值并被门禁实守。

本需求 SHALL NOT 改变 `槽位抽取完整率` 的「存在性口径」（只看期望槽位键是否被抽出、不比精确值），SHALL NOT 改变子 Agent 行为、系统提示或任何 `services/` / `harness/runtime` 业务逻辑——唯一杠杆是用例（数据集）本身。

诚实边界 SHALL 保留：本需求降低而非消除回落概率；当某次跑因 LLM 非确定性致全部相关用例罕见地均未触发工具时，`槽位抽取完整率` 仍按既有 skipped 语义处理、报告如实给出当次实守项数，MUST NOT 把「稳定守 3 项」表述为「绝对永不回落」。

#### Scenario: 信息齐全的祈使式预约用例具有可观触发概率

- **WHEN** 在 API key 可用时对一条信息齐全的祈使式预约用例（精确时间 + 项目 + 点名具体技师等）多次真跑 `AgentLoop`
- **THEN** 该用例在相当比例的跑次中触发领域工具（如 `find_technician` / `check_availability`），`actual_slots` 从工具调用 args 还原出非 None 的槽位 dict 并计入 `槽位抽取完整率`；单条触发为 LLM 非确定行为、不要求恒触发，故策展靠**足量此类用例的冗余**而非任何单条的确定性

#### Scenario: 常规门禁跑稳定实守 3 项

- **WHEN** 以 `uv run python evals/run_evals.py --gate --samples 3` 运行
- **THEN** `槽位抽取完整率` 产出真值（非 N/A），门禁报告如实标注当次实守 3 项（意图分类准确率、工具调用-F1、槽位抽取完整率）

#### Scenario: 存在性口径与子 Agent 行为不变

- **WHEN** 应用本需求策展用例后检视评估口径与业务代码
- **THEN** `槽位抽取完整率` 仍按存在性口径判定（键存在即命中、不比值），且 `harness/subagents/` 子 Agent 提示与 `services/` 业务逻辑未被改动

#### Scenario: 罕见全未触发时诚实回落

- **WHEN** 某次跑因 LLM 非确定性致全部带 `expected_slots` 的预约用例均未触发任何工具
- **THEN** `槽位抽取完整率` 按既有 skipped 语义标「无法比对」，报告如实给出当次实守项数（回落为 2），不据此判失败也不夸大为「已守 3 项」
