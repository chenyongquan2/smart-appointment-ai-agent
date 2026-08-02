## Why

OnCall 路线第 2 期。目标是把「域」收敛成**可装载的包**，为 oncall 域腾出位置——否则第 3 期加 `vlog_query` / `code_analysis` / `mt_docs_search` 时，两个域的工具会混在同一个 registry 与同一段 system prompt 里，"换域"就无从谈起。

路线图的核心判断是「**换域 = 换四样东西**：工具集 + system prompt + 权限策略 + eval 数据集；运行时（TAO 循环、记忆、护栏、Tracer）一行不动」。现在这四样全是散的：

| 换域要换的东西 | 现在在哪 | 问题 |
|---|---|---|
| 工具集 | `harness/tools/` 下 5 个预约工具 + `registry.build_default_registry()` 写死 | 域内容混在域无关的 harness 里 |
| 子 Agent | `harness/subagents/{appointment,consultant,user_behavior}.py` + `build_default_subagent_registry()` 写死 | 同上（`base` / `delegate` / `registry` 是域无关的，要留下） |
| system prompt | `harness/runtime/system_prompt.py` 的 `BASE_SYSTEM_PROMPT` 硬编码"按摩/推拿门店" | 同上（`build_system_prompt()` 本身域无关，要留下） |
| 权限策略 | `harness/guardrails/permission.py` 有闸门，但**生产路径根本没接**（`api/chat_handler.py` 一处 policy 都没传，实际走 `allow_all` 默认） | 没有归属地；而 oncall 的"全工具只读"红线要靠它硬 enforce |
| eval 数据集 | `evals/cases.jsonl` + `baseline.json` | 与运行器混在一个目录 |

顺带解决一笔陈年技术债：`harness/tools/technician.py` 横向依赖 `agents/appointment/technician_finder.py`，模块 docstring 里写着"Phase 3 迁移技师查找逻辑下沉后即可去除"——一直没做。它挡着 pre-harness `agents/` 遗留层（约 2031 行）的清理。反正都是搬，一次搬到位。

## What Changes

- **新增 `domains/` 结构**：每个领域包提供五个槽位——`tools/`（工具集）、`subagents/`（子 Agent 定义）、`prompt.py`（域人设与红线）、`policy.py`（权限策略）、`evals/`（用例集 + baseline）。
- **新增 `Domain` 装载契约**：一个域声明自己的五样东西，由**配置**决定装哪个（环境变量 `AGENT_DOMAIN`，缺省 `appointment`）。运行时代码 MUST NOT 出现 `if domain == ...`。
- **预约域整体下沉为 `domains/appointment/`**：5 个工具、3 个子 Agent、`BASE_SYSTEM_PROMPT`、eval 数据集全部搬过去。**纯搬迁，行为不变。**
- **`harness/` 只留域无关的部分**：`ToolRegistry` / `Tool` / `build_system_prompt()` / `SubAgentRegistry` / `SubAgent` / `delegate` / 记忆 / 护栏 / Tracer 保留；`build_default_registry()` 与 `build_default_subagent_registry()` 这两个**内容写死**的工厂由域装载取代。
- **`TechnicianFinder` 从 `agents/` 下沉到 `services/technician_matching.py`**，去掉 `harness/tools/` 对 `agents/` 的横向依赖（分层重归"单向向下"）。
- **删除 pre-harness 的 `agents/` 遗留层**（约 2031 行）：`agents/appointment_agent.py` + `agents/appointment/`、`agents/user_behavior_agent.py` + `agents/user_behavior/`，及喂它们的遗留端点 `api/appointment.py` / `api/user_behavior_analysis.py`。**BREAKING**：这两个 HTTP 端点下线（主对话路径 `api/chat_handler.py` 与飞书 channel 不受影响）。
- **权限策略获得归属地**：`domains/appointment/policy.py` 显式声明当前的 `allow_all`，并把它**接进生产路径**。这是把今天隐式的行为写明，**不改变任何判定结果**；oncall 域在第 3 期声明只读策略时，接线已经就位。

## Capabilities

### New Capabilities
- `domain-packages`: 领域包的结构、装载契约与配置切换；运行时对域的无知性（MUST NOT 出现域名分支）。

### Modified Capabilities
- `tool-layer`: 「核心工具集」不再由 harness 写死枚举，改为**由当前装载的领域包提供**；`ToolRegistry` 本身与工具定义结构不变。
- `subagent-delegation`: 三个子 Agent 的定义归属从 `harness/subagents/` 迁到领域包；`SubAgent` / `SubAgentRegistry` / `delegate` 工具的机制不变。

## Impact

**新增**：`domains/`（`__init__.py` 装载器 + `appointment/` 包）、`services/technician_matching.py`。

**改动**：`harness/tools/registry.py`（删 `build_default_registry`）、`harness/subagents/registry.py`（删 `build_default_subagent_registry`）、`harness/runtime/system_prompt.py`（`BASE_SYSTEM_PROMPT` 移出，函数签名改为接收域提示）、三处运行时组装点（`api/chat_handler.py`、`evals/agent_capture.py`、以及 executor/channel 若有间接引用）。

**删除**：`agents/`（整层）、`api/appointment.py`、`api/user_behavior_analysis.py`、`harness/tools/*.py` 与 `harness/subagents/{appointment,consultant,user_behavior}.py`（移动而非消失）。

**测试**：涉及 import 路径变化的用例批量更新；新增领域装载的测试（装载器返回五样齐全、切换域时运行时无需改动、未知域名报错）。**行为断言一律不动**——搬迁若需要改断言，说明不是纯搬迁。

**评估**：`evals/cases.jsonl` 与 `baseline.json` 移入 `domains/appointment/evals/`（**内容一字不改**，只改路径）。按 [预约域评测冻结决策](../../../docs/oncall-bot-roadmap.md) 不重定基线、不扩用例。

⚠ **验收口径要诚实**：本期的网只有 `uv run pytest`，而 pytest 用 fake LLM、**不会推理"该调哪个工具"**。工具层重构后"模型是否仍选对工具"覆盖是弱的——这是冻结决策下知情接受的风险。收尾时至多跑一次现有 `--gate`（用现成数据与基线，零新增数据工作），**不得**声称"全绿即证明无损"。
