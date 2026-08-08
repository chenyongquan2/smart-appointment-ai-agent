## Context

`domain-packages` 立下的分界是「机制域无关、数据随域走，换域只放两个数据文件」。核实下来这条分界有三处漏水，都在评估路径上：

| 位置 | 硬编码内容 | 装上 oncall 数据的后果 |
|---|---|---|
| [evals/run_evals.py:73](../../../evals/run_evals.py:73) `VALID_INTENTS` | 5 类预约意图 | `load_cases` 对不在白名单的 `expected_intent` **硬 `SystemExit(2)`**——用例加载不进来 |
| [evals/metrics.py:351](../../../evals/metrics.py:351) `_SLOT_ARG_KEYS` | `start_time` / `technician_name` / `project` / `duration` / `gender` | oncall 工具无这些入参 → `actual_slots` 恒空 |
| [evals/metrics.py:721](../../../evals/metrics.py:721) `GATED_METRICS` | `{工具调用-F1, 槽位抽取完整率}` | 第二项恒 N/A → 门禁**静默**退化成只守 1 项 |

第三条最危险：它不报错，只是安静地少守一项，报告里看起来一切正常。

约束：预约域即将下线但**尚未**下线，本次改动必须保证它行为与基线数字一字不动（否则要重定一个即将废弃的域的基线，纯浪费）。值守域无子 Agent（`SUBAGENTS` 为空），主 Agent 直接持六工具。

## Goals / Non-Goals

**Goals:**
- 值守域有一套能跑、能守、能重定基线的评估用例集，接替预约域的回归网角色
- 把三处域耦合收进领域包声明，使「机制域无关」真正成立、且**违反时显式失败而非静默降级**
- 预约域零行为变化、零基线重定

**Non-Goals:**
- 覆盖 `回复质量通过率` 与 `任务成功率`（本次明确推迟，见 D7）
- 触碰指标算法、门禁比对算法、并发 runner、triage、dev/held-out 切分——这些确实域无关，一行不改
- 下线预约域（独立工作）
- 为 oncall 建 judge 校准集

## Decisions

### D1：三项声明收进一个 `EvalProfile`，而非往 `Domain` 平铺三个字段

`Domain` 现有 6 个字段已是「五样东西」的直译；再平铺三个评估相关字段会让它读起来像杂物袋，且这三项是同一个概念的三个面（「本域的评估标注口径」）。按项目「一个概念一个文件」的约定，新建 `domains/eval_profile.py` 放一个 frozen dataclass，`Domain` 只加一个 `eval_profile: EvalProfile` 字段。

**替代方案**：把三项塞进 `evals_dir` 旁边的一个 `profile.json` 数据文件。否决——它们要被代码校验（指标名拼错必须失败），放 JSON 等于把校验推迟到运行期且失去类型；且 `slot_key_map` 天然是代码常量而非配置。

### D2：`EvalProfile` 的校验发生在 `evals/` 侧，不在 `domains/` 侧

`gated_metrics` 声明的指标名必须真实存在，这个校验需要指标名全集——它在 `evals/metrics.py`。但依赖方向是 `evals → domains`（`run_evals.py` 里 `from domains import load_domain`），`domains` 反过来 import `evals` 会成环，也会违反单向分层。

故：`EvalProfile` 本身只做**结构性**校验（非空集、类型），**语义**校验（指标名是否存在、是否为被禁的说明性指标/延迟/未校准 judge 项）在 `evals` 侧拿到 profile 后立即执行，失败即报错退出 2（沿用「坏配置不静默」的既有退出码约定）。

### D3：oncall 第二道门禁用 `工具调用-参数级F1`，不用 `槽位抽取完整率`

这是本设计里最实质的一个判断，不是为省事换指标。

值守域六工具的判别性入参几乎全是**必填项或枚举**：`LocateServiceCodeArgs.service/env`、`CodeSearchArgs.service/env`、`ReadSourceArgs.service/env/path`、`MTDocsSearchArgs.platform`（必填枚举）、`LoadReferenceArgs.name`（必填枚举）。槽位完整率是**存在性**口径（键在即命中），而必填项只要工具被调用就一定在 → 该指标恒等于「工具调没调」，是 `工具调用-F1` 的影子，两项一起守等于同一信号守两遍，门禁的第二道形同虚设。

反过来，正因为这些值是枚举和短字面量（`prod`/`uat`、`mt4`/`mt5`、`ocs4-returncode`、服务名），**精确值比对**在这里是成立的——而这恰是预约域参数级 F1 只有 11.1% 的原因的反面：预约域的值是自由文本（`start_time` 常被模型算错日期、`gender='男'` 而非 `male`），精确比对几乎恒 miss。同一个指标，在两个域的适用性正好相反。

唯一 Optional-without-default 的判别性入参是 `VlogQueryArgs.env`，单它一个撑不起一道门禁。

**替代方案**：给 oncall 硬凑一份 `slot_key_map`（把必填项也算槽位）。否决——那是制造一个恒 ~100% 的指标来充数，属于粉饰门禁。

故 oncall 的 `slot_key_map` **声明为空**，语义是「本域不度量槽位完整率」，指标恒 N/A 且不得进门禁（spec 里写死这条约束，防止将来有人把空映射和"忘了配"混为一谈）。

### D4：带 schema 默认值的入参一律不进期望标注

`window`（默认 `6h`）、`limit`、`glob`、`sync`、`context_lines`、`start_line`、`line_count` 都有默认值，模型不给也会出现在 args 里。把它们标进 `expected_tool_args` 会让参数级 F1 白拿分。这与既有「哨兵值 `未知`/`无` 不算已填」是同一条原则的延伸——**默认值不是模型的抽取成果**。

自由文本入参（`term` / `pattern` / `query` / `logsql`）同样不标，理由相反：语义等价形态太多（查同一个 traceId 可以 `term=["abc"]` 也可以 `logsql`），精确比对会恒 miss。

结论：oncall 的 `expected_tool_args` 只标 `service` / `env` / `platform` / `name` / `path` 这几个枚举或短字面量键。

### D5：oncall 用 5 类标签，不省掉标签

标签在本项目里不喂任何分类器（旧分类器已退役），只做数据集构成约束、按类分项分析、切分规则。既然如此，能不能干脆不标？不能——没有标签就没有「每类不少于 N 条」这条覆盖约束，用例集会不知不觉地全长在最容易写的 `vlog_query` 上。5 类按工具族划分（`log_triage` / `code_lookup` / `docs_lookup` / `reference_lookup` / `other`），刻意与工具集对齐，使覆盖约束直接翻译成工具覆盖。

### D6：先手写骨架，再从 trace 回灌，不等真实流量

工具 F1 与参数级 F1 这两层度量的是「有没有调对工具、参数给没给对」，**与工具返回什么无关**——这在 `remove-local-rag` 那次已被实证（知识库整个拆走，工具 F1 零影响）。故这两层不依赖真实语料，也不依赖真实流量，手写即可立起来。

现存 3 份真实 oncall trace（`vlog_query` 58 次 + `load_reference` 12 次）经 triage 回灌补真实形态。值守域无子 Agent，故 triage 那条已知局限（「子 Agent 各自开 root span，候选挂不回原始用户输入」）**在本域不适用**，回灌链路是干净的——这是无子 Agent 结构的一个意外收益。

### D6b：用例的期望必须与系统提示一致，否则量的是提示词而非模型

实现期读 `domains/oncall/prompt.py` 时发现两处会让「想当然的标注」失真，用例据此调整：

- **「查日志 → 看源码」不作单轮组合用例**。系统提示写死了「下钻到需要看源码才能定位时：
  给出日志层结论 + 线索，**本轮不做源码分析**」。标这条单轮链路，期望的是一个被刻意
  抑制的行为，压低的是指标而非模型能力。该链路天然多轮，随多轮用例一并推迟。
- **`mt_docs_search` 的用例只能是 Manager API 语义问题**，不能是返回码问题。分诊表规定
  三层查法：自研码查 reference → 平台原生码先查本地 `mt-returncode` 速查表 → **速查表
  没覆盖才用 `mt_docs_search`**。拿「MT_RET_REQUEST_INVALID 是什么」当 `mt_docs_search`
  的锚点，期望的恰是分诊表禁止的那一步。

一般化的教训：**锚点用例的期望工具必须与系统提示的分诊规则一致**，否则量到的是「提示词
和用例谁写得对」，不是模型能力。这条对将来任何域建用例集都成立。

### D7：`回复质量通过率` 与 `任务成功率` 明确不覆盖

- **任务成功率**：口径是「业务终态工具被调用且执行未失败」。六工具全为只读检索，没有 `create_appointment` 那样的事务终态——「查到了想要的日志」不是一个工具能判定的事实。硬标一个终态工具等于把「调用成功」重命名为「任务成功」，是伪造分母。
- **回复质量**：judge 未校准（既有诚实原则已排除它进门禁），且值守回复的正确性依赖代码仓 / MT 文档库 / 日志数据的**当下内容**，语料一漂移同一条用例的正确答案就变了，离线判定不成立。

两者在 README 如实标注不覆盖，不以任何形式暗示已覆盖。

### D8：容差不沿用预约域的 `0.30`，定基线时按实测半宽校准

`0.30` 是预约域按其**实测最差半宽**（槽位 ±28.7pp）定的，与 oncall 无关。参数级 F1 在 oncall 上的 run-to-run 方差**目前无任何观测**。故定基线时用 `--samples 3` 记录两项的 95% t-CI 半宽，容差取覆盖实测最差半宽的值；`n=3` 的半宽估计本身不稳（t 临界 4.303），故沿用预约域那条经验：取历次最差而非最新一次，且 MUST NOT 追着最新数字上下调。

### D9：预约域零变化的保证方式

`appointment` 的 `EvalProfile` 三项**填的就是当前硬编码值**（5 类标签、6 项槽位映射、`{工具调用-F1, 槽位抽取完整率}`），故行为等价、基线数字不动、**不重定预约域基线**。`tests/` 中断言全局 `GATED_METRICS` 的守护测试改为「按域取」后断言同样内容。这条要有测试守住，不能靠肉眼比对。

## Risks / Trade-offs

- **[跨工具链路用例依赖真实语料可用]** `locate_service_code` / `code_search` / `read_source` 需要 `repos/` 与 git worktree，`mt_docs_search` 需要文档库；评估环境缺这些时工具执行失败。对 F1 与参数级 F1 **本身零影响**（两者只看调没调、参数给没给对，不看返回值），但工具失败会改变模型后续行为——链路用例的第二、三个工具可能因此不被调用，间接压低 F1 → **缓解**：定基线前先确认这些语料在评估环境可用；不可用时该跑次不得落盘基线（同「环境故障不得据以定基线」的既有约束）。
- **[vlog_query 打真实日志网关]** 评估会产生真实（只读）查询流量，并发 5 × 采样 3 会放大到数百次查询 → **缓解**：oncall 用例集的 `vlog_query` 锚点一律给窄 `window`；定基线时视网关表现下调 `--concurrency`。
- **[参数级 F1 方差未知]** 它可能比槽位完整率更抖（依赖模型把 `env`/`platform` 给对） → **缓解**：D8 的实测校准；若实测半宽大到容差失去意义，退路是门禁只守 F1 并**如实记录**只守 1 项，MUST NOT 用一个恒满分的假指标充数。
- **[3 份 trace 太少]** 回灌只能当种子，撑不起统计意义 → **缓解**：手写骨架承担规模，trace 只补形态；README 如实标注用例集为「手写为主 + 少量真实种子」，不宣称代表真实分布。
- **[预约域下线时机可能早于本 change 落地]** 届时要同时改两个域的声明 → **缓解**：本 change 与下线互不阻塞；若下线先落地，删掉 appointment 的 `EvalProfile` 即可，`EvalProfile` 机制本身不受影响。

## Migration Plan

1. 加 `EvalProfile` 与 `Domain.eval_profile`，两个域各自声明（appointment 填现值）——此步单独跑 `uv run pytest`，确认预约域行为等价。
2. `run_evals.py` / `metrics.py` 三处硬编码改读 profile，加语义校验与失败路径。仍在预约域下跑 `--gate`，确认判定与改动前一致。
3. 写 oncall `cases.jsonl` 骨架用例 → `--limit` 冒烟 → triage 回灌 trace 种子。
4. `--samples 3 --update-baseline` 定 oncall 基线，记录两项半宽并据此定容差。
5. 更新 `evals/README.md`：值守域章节、覆盖边界、两域指标不可比的警告。

**回滚**：第 1–2 步是纯重构，回滚即还原三处常量；第 3–5 步只新增两个数据文件，删除即回到现状。

## Open Questions

- 预约域正式下线时，其 `EvalProfile` 与 `domains/appointment/evals/` 一并删除——需不需要在删除前把「41 条用例 + 基线」归档留档（作为历史参照），还是随域一起弃掉？倾向随域弃掉（两域数字不可比，留着无参照价值），但这属下线那个 change 的范围。
- oncall `cases.jsonl` 里是否需要多轮（`turns`）用例？值守的真实交互常是「贴一段日志 → 追问下钻」的多轮形态，但多轮触发比单轮更不稳定。倾向本次先全单轮、把多轮留作后续切片，除非 trace 回灌出的种子天然是多轮。
