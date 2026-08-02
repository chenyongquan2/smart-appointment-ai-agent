> **搬迁纪律（贯穿全程）**：本变更是纯搬迁 + 接线重排，**不改任何行为**。
> 允许改的只有 import 路径与装配代码；**若某处需要修改行为断言，立刻停下**——那说明它不是纯搬迁。
> 建议提交拆成两个：先 `git mv` + 改 import（`git log --find-renames` 可看清），再改装配逻辑。

## 1. TechnicianFinder 下沉（清横向依赖债，为删遗留层铺路）

- [x] 1.1 新建 `services/technician_matching.py`，把 `agents/appointment/technician_finder.py` 的 `TechnicianFinder` 整体搬入。**函数体一行不改**——它刚在 `fix-technician-embedding-blocking` 里改成 async，同批代码短期两次改动会让 `git log` 说不清问题出处。
- [x] 1.2 `harness/tools/technician.py` 改为 `from services.technician_matching import TechnicianFinder`；删掉模块 docstring 里那段"本工具临时横向依赖 `agents/`，违反严格的单向向下，Phase 3 迁移后即可去除"——这次兑现了，改为记一句"曾横向依赖 agents/，已于 change domain-packages 下沉到 services/"。
- [x] 1.3 ✅ 已做（`appointment_processor.py` 与 `appointment_agent.py` 都改了指向），中间态保持可跑。
- [x] 1.4 更新 `tests/test_harness_tools.py` 等对 `agents.appointment.technician_finder` 打桩的用例，改打 `services.technician_matching`。
- [x] 1.5 `uv run pytest` 绿。

## 2. 建 domains/ 骨架与装载契约（旧工厂仍在，可并存验证）

- [x] 2.1 新建 `domains/__init__.py`：`Domain` frozen dataclass（`name` / `tools` / `subagents` / `system_prompt` / `policy` / `evals_dir`）+ 显式注册表 `_DOMAINS = {"appointment": ...}` + `load_domain(name=None)`（读 `AGENT_DOMAIN`，缺省 `appointment`；**未知域名抛错并列出可选值，MUST NOT 静默回落**）。
- [x] 2.2 注册表的值是**无参工厂函数**而非模块级实例——装 A 域不该连带拉起 B 域的重型依赖（第 3 期 oncall 会拖着 VictoriaLogs / git worktree）。
- [x] 2.3 建 `domains/appointment/` 包：`tools/`（从 `harness/tools/` 搬 5 个工具 + `schemas.py` + `time_utils.py`）、`subagents/`（从 `harness/subagents/` 搬 appointment / consultant / user_behavior 三个定义）、`prompt.py`（承接 `BASE_SYSTEM_PROMPT`）、`policy.py`（显式声明 `POLICY = allow_all`）、`evals/`（暂空，第 5 组填）。
- [x] 2.4 **留在 harness 的东西别搬错**：`tools/base.py`（`Tool` / `NO_TIMEOUT`）、`tools/registry.py`（`ToolRegistry`）、`subagents/base.py`、`subagents/registry.py`（`SubAgentRegistry`）、`subagents/delegate.py`、`runtime/system_prompt.py` 的 `build_system_prompt()`。判据：**换成 oncall 域还成立吗？** 成立就留下。
- [x] 2.5 新增 `tests/test_domain_loading.py`：五样齐全、缺省装 appointment、`AGENT_DOMAIN` 可切换（用一个测试用假域验证）、未知域名抛错且错误信息列出可选值、运行时无域名分支。

## 3. 三处组装点切到 load_domain，删旧工厂

- [x] 3.1 `harness/runtime/system_prompt.py`：签名改为 `build_system_prompt(base_prompt, registry, subagents=None)`，`BASE_SYSTEM_PROMPT` 移出到域包。**刻意不让函数内部去 `load_domain()`**——那会把纯函数变成依赖全局状态的函数（见 design D4）。
- [x] 3.2 `api/chat_handler.py:50-79`：改为 `domain = load_domain()` 后由其内容拼 registry / subagents / prompt / policy；`ToolRegistry` 传入 `policy=domain.policy`（**首次把权限闸门接进生产路径**，判定结果不变，见 design D5）。
- [x] 3.3 `evals/agent_capture.py` 的 `_build_capture_loop`：同款改造。
- [x] 3.4 **删除** `harness/tools/registry.py::build_default_registry` 与 `harness/subagents/registry.py::build_default_subagent_registry`——**不留兼容壳**：漏改的调用点要直接 ImportError 暴露，而不是悄悄用着旧的写死工厂。
- [x] 3.5 全仓搜这两个函数名与 `BASE_SYSTEM_PROMPT`，确认无残留引用（含 `tests/`、`channels/`、`executor/`）。
- [x] 3.6 新增测试：域声明的策略确实生效（装一个拒绝某危险工具的假域，断言 handler 未被执行、返回结构化拒绝）；预约域判定结果与改造前一致（放行）。
- [x] 3.7 `uv run pytest` 绿。

## 4. 删 pre-harness 遗留层

- [x] 4.1 删 `agents/appointment_agent.py` 与 `agents/appointment/`（`appointment_processor` / `input_parser` / `message_builder` / `schemas` / `appointment_database` / `technician_finder`——最后这个已于第 1 组下沉）。
- [x] 4.2 删 `agents/user_behavior_agent.py` 与 `agents/user_behavior/`（`behavior_recorder` / `pattern_analyzer` / `preference_manager`）。**先确认** `harness/` 或 `services/` 没有引用其中任何组件（`PreferenceManager` 尤其要查——长期记忆可能用到）。
- [x] 4.3 删 `api/appointment.py`、`api/user_behavior_analysis.py` 并从 `api/__init__.py` 摘除。**BREAKING**：这两个 HTTP 端点下线。⚠ **计划外补做**：删 API 后 `web/routes.py` 的 `/user_behavior`、`/user_behavior_analysis` 两个**页面路由**与模板 `user_behavior_analysis.html` 成了死页（页面还在、它调的接口没了），一并删除并摘掉首页导航按钮——与 remove-local-rag 处理知识库页同款。
- [x] 4.4 删 `agents/` 整个目录与 `agents/__init__.py`；删对应测试 `tests/test_appointment_agent.py`、`tests/test_user_behavior_agent.py`；清理 `tests/conftest.py` 的 `fake_llm_env` 里对这些模块的打桩。
- [x] 4.5 确认 `api/chat_handler.py`、`channels/lark/`、`executor/` 完全不受影响（主对话路径与飞书 channel 不引用 `agents/`）。
- [x] 4.6 起服务冒烟：`/chat` 与 `/chat/stream` 正常；`/api/appointment`、`/api/user_behavior_analysis` 已下线；首页无死链。
- [x] 4.7 `uv run pytest` 绿。

## 5. evals 数据入域包

- [x] 5.1 `git mv` `evals/cases.jsonl`、`evals/baseline.json` 到 `domains/appointment/evals/`。**内容一字不改**（含 `baseline.json` 里 mojibake 的中文指标名）——改路径同时改内容就没法证明是纯搬迁。
- [x] 5.2 `evals/run_evals.py` 等改为从 `load_domain().evals_dir` 取数据路径；`evals/` 下的运行器、采集、triage、并发 runner **全部保持域无关，原地不动**。
- [x] 5.3 更新 `evals/README.md` 的路径说明；点明「机制留在 `evals/`、数据随域走」这条分界，以及第 4 期建 oncall 用例集时只需往 `domains/oncall/evals/` 放两个文件。
- [x] 5.4 `git diff` 复核这两个数据文件只有路径变化、内容零 diff（`git log --find-renames` 应识别为纯 rename）。

## 6. 验证与收尾

- [x] 6.1 ✅ **450 passed / 0 xfailed**。差额逐条对上：改造前 443+9=**452** → 删 `test_appointment_agent.py` + `test_user_behavior_agent.py`（用 `git stash` 单独跑过，确认恰为 **8 passed + 9 xfailed = 17**，9 个 xfailed 全在这两个文件里）→ 新增 `test_domain_loading.py` **15** 条 → 452−17+15=**450** ✓ 无测试悄悄消失。
- [x] 6.2 grep 确认运行时无域名分支：`harness/`、`evals/`、`executor/`、`channels/` 里不存在 `== "appointment"` / `== "oncall"` 之类判断。
- [x] 6.3 grep 确认 `harness/` 里不再有域内容：无按摩/技师/预约相关的人设文本与工具定义。
- [x] 6.4 ⚠ **验收表述要诚实**：本期的网只有 pytest，而 pytest 用 fake LLM、**不会推理"该调哪个工具"**——工具层结构变了而"模型仍选对工具"这件事它验不了。按预约域评测冻结决策不为此投入新数据工作；至多跑一次现有 `--gate`（用现成数据与基线，零新增数据工作）。**结论写"pytest 全绿、选工具正确性未验证"，不得写"全绿即证明无损"。**
- [x] 6.5 更新 `docs/oncall-bot-roadmap.md`：第 2 期标记完成；`openspec/project.md` 的分层结构补上 `domains/` 与"换域 = 换五样（工具/子Agent/提示/策略/评估数据）"的说明。
- [x] 6.6 更新 `docs/harness-code-reading.md`：涉及 `harness/tools/` 与 `build_default_registry` 的讲解改为域包装载（那份文档是逐文件导读，路径变了必须跟）。


## 7. 实现期的计划外发现（如实记账）

- [x] 7.1 **`AgentLoop` 的缺省 system_prompt 是一处域泄漏**：`system_prompt=None` 时它直接引用 `BASE_SYSTEM_PROMPT`，等于把「你是一家按摩门店的智能助手」硬挂在域无关的运行时类上。领域包化才让它暴露。改为 `GENERIC_BASE_PROMPT`（不含任何业务词汇的最小基线）。⚠ 这**是**一处行为变更（仅影响"没显式传 system_prompt 就 new 了个 loop"的路径——生产与子 Agent 都显式传，故不影响线上）。
- [x] 7.2 **记忆层三处剩余域泄漏**（structural 测试抓出来的）：`summary_schema.py` 的 `Field(description=...)` 举的全是预约例子（"技师姓名"、"只要女技师"，会进 `model_json_schema()` 即写给模型的提示词）、`summary.py` 同源、`long_term.py` 的 `_TYPE_LABELS` 把 `technician→技师` 等预约概念硬编码。**本期不修**——它们不是"放错位置的域内容"（搬走就行），而是"域无关机制里嵌了域特定文本"，要清干净得让这些文本随域可配，属行为变更、越出纯搬迁纪律。已写进 `tests/test_domain_leaks` 白名单，且配一条 `test_known_domain_leaks_still_exist` 防止白名单烂掉（泄漏被清后该测试会失败，提醒删白名单）。
- [x] 7.3 **`build_tool_registry` / `build_subagent_registry` 两个装配辅助函数是计划外新增**：原设计只说 Domain 交出 tuple、由各组装点自己装。实际有 3+ 处要装，重复同一段循环不如收在 `domains/__init__.py`。仍是**函数**而非 `Domain` 的方法——保持 Domain 是纯数据，也让调用方能自由只装一部分（如主 registry 只放 delegate）。
