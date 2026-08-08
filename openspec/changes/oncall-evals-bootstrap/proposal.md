## Why

预约域即将下线，而它的 `cases.jsonl` / `baseline.json` 是**当前唯一**在守 TAO 循环 / ToolRegistry / 护栏的自动回归网——一旦移除，`/phase` 闸门 2 会退化成空转（缺基线只警告不阻断），值守域的任何行为回归都将无人察觉。值守域已是主用域（`AGENT_DOMAIN=oncall`），六个工具全部就位并在真实群聊跑通，却零评估覆盖：近期换 LLM（`deepseek-v4-flash` → `z-ai/glm-5.2-free`）时无任何自动信号可用，只能靠手动开群聊验，这就是缺口的第一次实际代价。

同时，`domain-packages` 声称的「评估机制域无关、换域只需放两个数据文件」**经核实并不成立**：机制里仍有三处硬编码的预约域概念，装上 oncall 数据会直接失败或静默降级（见下）。本次一并补上，让那条分界名副其实。

## What Changes

- **新建 `domains/oncall/evals/cases.jsonl`**：手写骨架用例，覆盖六工具（`vlog_query` / `load_reference` / `locate_service_code` / `code_search` / `read_source` / `mt_docs_search`）单工具触发与跨工具组合（定位源码 → 检索 → 读取 / 服务档案 → 查日志 / 错误码分诊 → 文档兜底），按 dev / held-out 切分。**「查日志 → 看源码」不作单轮组合用例**——系统提示明确要求那种情况「本轮不做源码分析」，标它等于期望一个被刻意抑制的行为。标 `expected_tools` 与 `expected_tool_args`，**不标** `expected_outcome`、**不标** `expected_slots`（理由见下）。
- **新建 `domains/oncall/evals/baseline.json`**：在新用例集上 `--samples 3 --update-baseline` 定基线，使 `--gate` 在 oncall 域可用。
- **从现有 trace 榨取种子用例**：`evals/traces/` 现存 3 份真实 oncall trace（`vlog_query` 58 次 + `load_reference` 12 次），经 `evals.triage` 的 `scan` → 人工标真值 → `append` 回灌，补手写想不到的真实形态。值守域**无子 Agent**（`SUBAGENTS` 为空），故 triage 那条「子 Agent 各自开 root span、候选挂不回原始用户输入」的已知局限在本域**不适用**，回灌链路是干净的。
- **把评估机制里三处预约域硬编码收进领域包声明**（这是「机制域无关」的欠账，不是新功能）。新增一个 `EvalProfile` 声明对象挂到 `Domain`，含三项：
  - **标签白名单**——`run_evals.py` 的 `VALID_INTENTS` 写死 5 类预约意图，且 `load_cases` 对不在白名单的 `expected_intent` **硬退出 2**，oncall 用例根本加载不进来。
  - **槽位键映射**——`metrics.py` 的 `_SLOT_ARG_KEYS` 写死预约槽位名（`start_time` / `technician_name` / `project` / `duration` / `gender`）。
  - **门禁指标集**——`GATED_METRICS` 写死 `{工具调用-F1, 槽位抽取完整率}`。
- **oncall 门禁改守 `{工具调用-F1, 工具调用-参数级F1}`**，槽位完整率对本域**按设计标 N/A**。理由是口径而非省事：oncall 六工具的判别性入参（`env` / `platform` / `service` / `load_reference.name`）**几乎全是必填项或枚举**，「存在性」口径下只要工具被调用就恒命中，该指标会退化成 F1 的影子、不提供新信号；而这些值是枚举/短字面量，恰好是**精确值比对**成立的场景——预约域参数级 F1 只有 11.1% 是因其值为自由文本（`start_time` 常算错、`gender='男'`），这个毛病 oncall 没有。带 schema 默认值的入参（`window` / `limit` / `glob` / `sync` 等）MUST NOT 进任何期望标注——默认值恒存在，会把指标虚高。
- **明确推迟两层并在 README 如实标注**：`回复质量通过率`（需真问题真答案）与 `任务成功率`（六工具全为只读检索型，无事务终态可判；且判定随代码仓/文档库语料漂移）本次**不覆盖**，不伪造分母。

## Capabilities

### New Capabilities
- `oncall-evals`: 值守域评估用例集的口径——标签分类、覆盖哪些工具与组合、标注哪些字段、门禁守哪两项、哪些指标层明确不覆盖，以及用例集与真实语料的耦合边界。

### Modified Capabilities
- `eval-harness`: 标签白名单、槽位键映射、门禁指标集三者从机制侧硬编码改为读领域包声明；「预约类用例策展以稳定触发工具链」那条需求的域绑定表述泛化为「各域自行策展锚点用例、并声明本域实际可守的门禁项」。
- `domain-packages`: 领域包的第五样东西从「评估数据目录」扩为「评估数据目录 + 评估标注口径（`EvalProfile`）」，使「换域 = 换五样东西、运行时一行不动」在评估路径上真正成立。

## Impact

- **新增**：`domains/oncall/evals/{cases.jsonl,baseline.json}`、`domains/eval_profile.py`（`EvalProfile` 声明类型）
- **修改**：`domains/__init__.py`（`Domain` 加 `eval_profile` 字段）、`domains/appointment/__init__.py` 与 `domains/oncall/__init__.py`（各自声明）、`evals/run_evals.py`（`VALID_INTENTS` 去硬编码）、`evals/metrics.py`（`_SLOT_ARG_KEYS`、`GATED_METRICS` 去硬编码）、`evals/README.md`（覆盖边界与读法）
- **不动**：`agent_capture.py` / `trace_collect.py` / `triage.py` / 并发 runner / 多采样 t-CI / dev-held-out 切分 / 门禁比对算法——这些确实域无关
- **预约域**：加字段需同步补预约域声明，填的就是现值，故其 41 条用例与基线**行为不变、数字不动**，**不需要重定预约域基线**；`tests/` 中断言 `GATED_METRICS` 的守护测试需跟着改成「按域取」
- **风险**：oncall 单条工具触发同样是强非确定行为（预约域实测单条触发率约 0.27），稳定性只能靠数据集冗余而非改写单条；参数级 F1 的容差需在定基线时按实测半宽另行校准，**MUST NOT** 直接沿用预约域的 `0.30`；新基线的绝对数字与预约域**不可比**（工具名都不同）
