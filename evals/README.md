# evals/ — 重构回归评估集（Phase 0）

> 开发期 harness 的**验证回路**核心。用例集贯穿整个重构;**评分指标随阶段演进**(见下方 ⚠️)。
> 配套：[../docs/harness-refactor-plan.md](../docs/harness-refactor-plan.md) 的 Phase 0。

> ⚠️ **用例集长期复用，但"评分指标"随阶段演进——别把意图准确率当永久指标。**
> - **Phase 1–2（分类器仍在）**：意图分类准确率是**有效的退化对照**(Phase 1 结构化输出正是要改进它,验收口径就是分类错误率)。
> - **Phase 3 ReAct/TAO 起**：意图分类并入 loop(意图隐含在"调了哪些工具"里)，评分改用**工具调用准确率 → 端到端结果（约对没约对）**(见 `expected_tools`；plan 的 Phase 3 验收口径也是"端到端通过率≥基线")。
> - **change `retire-legacy-intent-classifier`（本节预言的兑现）**：旧分类器删除、意图准确率正式退役、门禁改守 2 项（工具 F1 + 槽位完整率）。
> 耐用资产是**这批行为级用例 + 运行器框架**(与实现解耦)，而非某个准确率数字本身。

## 这是什么

一套**可复用的行为评估用例集 + 运行框架**——以 `输入 → 期望行为` 为用例，在把 `agents/` 重构为 `harness/` 的过程中**客观衡量**系统行为有没有退化，而不是靠"感觉还行"。用例集是**耐用资产**；评分模式随阶段演进（见上方 ⚠️）。

## 意图口径（5 类）

> （change `retire-legacy-intent-classifier`）旧分类器已删除；`expected_intent` 现为**纯数据集标签**（构成约束/按类分析/切分规则用），不对应任何分类器组件。5 类口径本身不变：

| 意图 | 含义 |
|------|------|
| `appointment` | 预约任务（用户预约 / 工作人员告知延长服务等） |
| `query` | 查询任务（咨询价格、项目、技师、位置等） |
| `pay` | 支付任务（已选定技师/项目，待支付） |
| `statistics` | 统计任务（工作人员上报已完成） |
| `other` | 与按摩服务无关 |

> 注意：`config/constants.py` 的 `StateEnum` 是另一套 4 类口径（classify/appointment/consult/other），与分类器不一致。评估以**分类器的 5 类**为准；统一二者留待后续。

## 文件

- `cases.jsonl` — 评估用例（一行一条 JSON；`//` 开头为注释，运行时跳过）。
- `run_evals.py` — 运行器：接入真实 `TaskClassifier`，逐条比对 `expected_intent`，输出准确率基线 + 按类目分项 + 错误清单。

## 用例格式

**单轮**（`input` 为单条话语）：

```json
{"input": "我想预约明天下午的按摩", "expected_intent": "appointment", "expected_tools": ["find_technician", "check_availability"]}
```

**多轮**（`turns` 为有序话语列表；与 `input` 互斥，change `evals-multiturn-cases`）：

```json
{"turns": ["我想预约按摩", "明天下午2点，约李师傅，帮我订好"], "expected_intent": "appointment", "expected_tools": ["find_technician", "check_availability", "create_appointment"], "expected_slots": {"start_time": "明天14:00", "project": "按摩", "technician": "李师傅"}}
```

- 一条用例 **恰好提供 `input` 或 `turns` 之一**（皆有/皆缺 → 运行器报行号退出 2）。单轮 `input` 等价单元素 `turns`。
- 多轮的 `expected_tools` / `expected_slots` 口径为**整段对话累计**（跨所有轮次合并）；**意图对首轮判定**，故 `expected_intent` 跟随首轮（如「先咨询后预约」首轮是 `query` 即标 `query`）。
- 多轮采集口径：运行器按轮驱动**同一** AgentLoop，轮间只累积 user/assistant 文本对作 `history`（对齐生产 `chat_handler` 窗口，不回灌轮内中间工具消息——已知简化），跑完从同一 exporter 沙盒**跨所有轮次**还原工具序列与槽位，judge 用**末轮**回复。多轮触发比单轮更不稳定，沿用「数据集冗余 + `--samples` + 容差」稳住（同改造 8 切片 1 的诚实边界）。
- `expected_tools` 自改造 1 起**已计分**（端到端真跑采集 `actual_tools`）。
- `split`（可选，change `evals-dataset-scaleup-heldout`）：`"dev"`（缺省）| `"held-out"`——见下方「dev / held-out 切分」。缺省即 `dev`，既有用例不改一字即属 dev。
- `expected_outcome`（可选，change `evals-task-success-rate`）：业务**终态工具名**（appointment→`create_appointment`、query→`search_knowledge`）——见下方「任务成功率」。无工具终态的意图（pay/statistics/other）不标。

## 任务成功率（系统级/业务级，change evals-task-success-rate）

补齐评估分层最上面的一层——不只问「意图/工具调对没」，而是问**任务办成了没**。

- **口径**：用例标 `expected_outcome`（终态工具名）；一条用例「成功」= 该终态工具在端到端真跑中被调用**且执行未失败**（失败 = 其 observation 以「工具执行失败」开头，复用改造 7 口径）。仅标注了且捕获到工具执行的用例计入，宏平均、缺数据 N/A。
- **采集**：`evals/trace_collect.py:collect_tool_outcomes` 直接采 span 的 `observation` 事件（payload 自带 `name`+`result`），跨轮、跨子 Agent。
- **v1 不纳入门禁**：任务成功依赖工具触发、是强非确定项，先只打印观察；不在 `GATED_METRICS`，`--gate` 不因它退出非零。
- ⚠️ **诚实边界**：这是**离线任务完成度代理**，不是真实转化率/满意度/人工介入率（那些需真实用户流量，属生产级）。实测 dev 集任务成功率约 20%（24 条期望建单/查询、仅 5 条真正成功完成终态）——这正是它暴露的、意图/工具指标看不到的「办没办成」缺口。

## 📁 数据在哪、机制在哪（change `domain-packages`）

**评估数据随领域包走，评估机制留在本目录。**

- 数据：`domains/<domain>/evals/{cases.jsonl,baseline.json}`（预约域即 `domains/appointment/evals/`）
- 机制：本目录的 `run_evals.py` / `agent_capture.py` / `trace_collect.py` / `triage.py` / 并发 runner —— **全部域无关**，从 `load_domain().evals_dir` 取数据路径

这正是「机制 ≠ 数据」那条分界的落地：OnCall 第 4 期建 oncall 用例集时，只需往 `domains/oncall/evals/` 放两个文件，本目录一行不用改。

## ⛔ 本用例集已冻结（2026-08-02 决策）

**不再向预约域评测投入新精力**：不扩用例、不重定基线、不恢复 `feat/evals-dataset-scaleup`（184 条扩容版，17/18 完成、卡在重定基线——已放弃，change 于 2026-08-03 close 进 `openspec/changes/archive/2026-08-03-evals-dataset-scaleup-v2-abandoned/`；分支保留但已合不进来，它改的 `evals/cases.jsonl` 现在的路径是 `domains/appointment/evals/cases.jsonl`）。

原因：项目正按 [../docs/oncall-bot-roadmap.md](../docs/oncall-bot-roadmap.md) 换域到 OnCall 值守，**预约域是要退役的**。为一个将退役的域打磨评估数据没有回报，且 `工具调用-F1 = 56.2%` 这类数字对 oncall **零参考意义**（工具名都不同，不可比）——谁拿它当 oncall 的目标都是误用。

**现在这套用例集的定位**：域无关运行时（TAO 循环 / ToolRegistry / 记忆 / 护栏）的**零成本回归网**。留着只因为不删的成本是零；一旦需要为它花时间，跳过。

**没白做的部分**：域绑定的只有 `cases.jsonl` 与 `baseline.json` 两个文件。多采样 t-CI、门禁、dev/held-out 切分、任务成功率口径、trace triage 闭环、并发 runner **全部域无关**，第 4 期建 oncall 用例集时直接复用——那时是**复用机制、重建数据**。

## ⚠ 知识库未接入期间的指标读法（change `remove-local-rag`，2026-08-02）

本地 RAG（SQLite+FAISS）已删除，`search_knowledge` 改走 [../services/knowledge_search.py](../services/knowledge_search.py) 的可替换端口；**独立 RAG 项目接入前**，每次检索都以「知识库尚未接入」明确失败收场（刻意不返回空列表——那会让模型当成「库里没有」而编造答案）。由此产生的指标变化必须按下面的口径读，**不要误判为模型能力退化**：

| 指标 | 影响 | 说明 |
|---|---|---|
| `工具调用-F1`（门禁） | **零影响** | 量的是「有没有**调对**工具」，与工具**返回什么**无关 |
| `槽位抽取完整率`（门禁） | **零影响** | 与知识库无关 |
| `任务成功率` | `query` 类归零 | 36 条标 `expected_outcome: search_knowledge` 的用例，终态工具执行必失败 |
| `回复质量通过率` | 下探 | 咨询类回复变成「如实告知未接入」，judge 大概率判不通过 |

- **未重定基线**，因为门禁两项一分不动（`cases.jsonl` / `baseline.json` 本次一行未改）。这与「改 `cases.jsonl` 必重定基线」不冲突——那条针对的是**数据集**变更，本次变的是被调用工具的**返回值**。
- **接入后的收益**：注入一个返回固定文档的 fake 端口，`query` 类即可获得**离线确定性**——评估不再被 embedding 网关的死活绑架。
- ⚠ **解耦只覆盖 `query` 类**：`appointment` 类仍会经技师专长相似度匹配（`services/text_embedding.py` 的 `find_best_match_indices`）打 embedding 网关，网关抽风时该类指标依然会失真。这是**已知的剩余缺口**，属独立后续工作。

## dev / held-out 切分（change evals-dataset-scaleup-heldout）

用例集分两个子集，防「在同一批数据上调 prompt / 策展用例」的过拟合：

- **dev**（缺省，未标 `split` 即归此）：日常调试、prompt 调优、门禁基线都基于它。
- **held-out**（标 `"split": "held-out"`）：**过拟合体检的留出集**，MUST NOT 参与任何调优或门禁——只在显式请求时评估、单独呈现。

```bash
uv run python evals/run_evals.py                    # 默认只评 dev（与本切片前行为等价）
uv run python evals/run_evals.py --include-heldout   # dev + held-out 都评，held-out 分集呈现
uv run python evals/run_evals.py --heldout-only      # 只评 held-out（体检用）
```

- **基线/门禁恒基于 dev**：`--update-baseline` / `--gate` 只用 dev 结果；即便同时传 `--include-heldout`，held-out 也**物理上进不了** `baseline.json`（运行器用 `_split_results` 在 `build_report` 前就把两个子集拆开，held-out 只走"分集呈现"分支）。`--heldout-only` 不含 dev，故禁止与 `--update-baseline`/`--gate` 同用（退出码 2）。
- **规模（本切片）**：dev **41 条**（每类 ≥5：appointment 20 / query 6 / pay 5 / statistics 5 / other 5），held-out **10 条**（覆盖全部 5 类，技师名与 dev 不重复）。仍是手写合成——统计意义提升但**不代表真实分布**，真实分布靠改造 7 在线回灌（后续）。held-out 才 10 条、CI 很宽，定位为"粗过拟合体检"而非结论，规模化留后续切片。

## 运行

```bash
uv run python evals/run_evals.py                   # 全量, 输出多指标报告（默认并发 5）
uv run python evals/run_evals.py --limit 5         # 冒烟, 只跑前 5 条
uv run python evals/run_evals.py --concurrency 1   # 串行基准路径（排障/对照）
```

- 产出基线需 **API key 可用**（`.env` 里配好 `MODEL_PROVIDER` 对应的 `*_API_KEY`）。
- 无 key 时运行器**优雅降级**：打印用例清单 + 提示，并以非零码退出，不崩。

### 并发执行（change `evals-concurrent-runner`）

用例之间无共享可变状态（每条一个独立 `Tracer` + `InMemoryExporter` 沙盒、`AgentLoop` 无状态），故用 `asyncio.gather` + 信号量受限并发。`--concurrency N` 默认 **5**。

- **实测提速**：全量 41 条 × 3 采样 从串行约 **57 分钟** → 并发 **18.4 分钟**（**3.1×**）；单次跑约 6 分钟。20 条子集上测得 4.5×，全量偏低是因含 8 条多轮长尾用例拖收尾。
- **为何默认 5 而非更高**：每条用例内部还会派生子 Agent，实际在途请求是并发数的数倍；网关限流阈值未知（重定基线期间实测到过 503 与 `APIConnectionError`）。5 已拿到收益大头，冒进的边际收益低、风险高。
- **三条硬约束**（有离线单测守，见 `tests/test_eval_concurrency.py`）：结果**与输入同序**（下游 `_split_results` 靠 zip 同序拆 dev/held-out，错位会把 held-out 算进 dev 基线）、**在途数 ≤ N**、**单条失败隔离**（异常在 `_run_case` 内吞成 N/A，不冒泡到 `gather`、不取消其它在途）。
- `--concurrency 1` 走**真串行**分支（非"信号量=1 的并发"），作为排障与对照的基准路径，行为与并发化之前等价。
- **DB 并发**：`db/base/session_manager.py` 用 `scoped_session`（线程局部），asyncio 单线程下协程共享同一 session 理论上有事务交错风险；只读与写入两轮冒烟（含 `create_appointment` 真写库）均**未出现** `database is locked` 或交错，真跑失败 0 条，故本次**未加固、`db/` 未改动**。并发度调高时应重新验证（风险随并发度上升）。
- ⚠️ **延迟口径**：并发下每条 `latency_s` 含资源竞争（实测 avg 27.0s→43.9s），**不可与串行跑的历史数字直接比较**；不做任何"扣除竞争"的补偿估算（无法诚实计算）。延迟不在门禁集，故不影响回归判定。
- ✅ **并发不改变比率型指标**（D5 对照验收）：全量 3 采样下 并发 vs 串行——工具 F1 56.2% vs 54.4%、槽位 87.7% vs 79.6%、序列 48.0% vs 46.3%、任务成功率 23.6% vs 20.8%、参数级 11.1% 持平；全部在实测半宽内且方向持平或略优。**若未来出现系统性劣化，MUST 判为实现缺陷（DB 交错/限流致失败增多）并修复，MUST NOT 接受为新常态后重定基线。**

## 意图准确率已退役（change `retire-legacy-intent-classifier`）

- 旧分类器（`agents/task_classification/`）在 harness 重构后退出主服务链路，评估继续真调它算准确率 = **门禁守着一个不服务用户的组件**。已连同 `api/task.py` 端点与专属测试一并删除。
- **不做"从工具选择反推意图"的替代指标**：harness 架构下"选对工具"与"意图理解正确"是同一件事，工具 name 级 F1 已覆盖该信号，反推指标是同一信号算两遍。
- **端到端延迟同步改口径**：旧口径实测的是分类器单次调用耗时（假端到端）；现改为端到端真跑全程耗时（多轮跨轮累计）。延迟不在门禁，无回归判定影响，但**新旧基线的延迟数字不可比**。

## 基线与回归门禁（改造 6）

把"人工跑人工看"升级为"自动拦不达标"。两条命令：

```bash
# 定基线：把本次跑分落盘为基线（建议配 --samples 3 取稳定均值）
uv run python evals/run_evals.py --samples 3 --update-baseline

# 守基线：跑完比对基线，被守指标回归则以退出码 3 结束
uv run python evals/run_evals.py --gate
```

- **基线文件**：`evals/baseline.json`（进 git、可追溯），记录**全部非 N/A 指标**的快照 + 元信息（用例数、采样次数、`schema_version`）。可经 `--baseline <path>` 改路径。
- **门禁只守正确性子集** `GATED_METRICS = {工具调用-F1, 槽位抽取完整率}`（2 项；意图分类准确率已随旧分类器退役，见上节）。**刻意排除**：
  - `端到端延迟`——机器/网络/API 负载相关，跨环境抖动大，非正确性信号；
  - `回复质量通过率`——来自**未校准** judge，按项目诚实原则不可当真值；
  - 工具调用的其余 5 个子指标——同一底层行为，只守 F1（name 级部分给分、平滑退化）即可。
  其余指标仍照常打印，只是不触发非零退出。
- **容差** `--tolerance`（默认 **`0.30`**）：比率即百分点（30pp），吸收 LLM 的 run-to-run 抖动。比率回归判定为 `当前 < 基线 − 容差`。**0.30 的依据（实测校准、非魔数）**：每次重定基线时观测被守指标的 95% t-CI 半宽（改造 3），容差取值须覆盖最差半宽。change `retire-legacy-intent-classifier` 重定时实测（41 条 dev × 3，干净跑）：**工具 F1 ±5.7pp（历史水位）、槽位抽取完整率 ±28.7pp**。槽位半宽超出原 `0.20`，故按实测上调至 `0.30`。
  - **槽位方差为何回升**：历史上它是 `100% ± 0.0%`（8 条祈使式预约锚点稳定全触发）；串行重定时为 `79.6% ± 28.7%`，说明模型行为相对上次定基线时有漂移、锚点不再稳定全触发。**治本方向是补更多预约锚点（数据集冗余，同 change `evals-stabilize-gate-three` 的思路）压低方差后回调容差**——属独立 change，未纳入本次范围。
  - **n=3 的半宽估计本身不稳，故容差取"历次最差"而非"最新一次"**：紧接着的并发重定实测为槽位 `87.7% ± 5.3%`（半宽大幅收窄）、工具 F1 `56.2% ± 12.0%`（反而放宽）。两次观测方向相反，印证 3 个点算出的 t 区间摇摆很大（t 临界值 4.303）。故 `0.30` 维持不动——覆盖历次观测到的最差半宽（槽位 28.7pp），MUST NOT 追着最新一次数字上下调。
  - **代价要说清**：`0.30` 比 `0.20` 更松，只拦得住**大幅回归**（工具链整体崩坏级）。这是「宁可漏报也不误报」的取舍——门禁若频繁误报会被绕过、失去意义。
  > ⚠️ **重定基线的前提条件**：半宽必须来自**正常网络下的模型抖动**。若跑基线时出现 `APIConnectionError` / embedding 渠道 503 等环境故障，会有大批用例记 N/A，制造出伪方差（实测污染跑：工具 F1 半宽 ±57.6pp、序列正确率 ±66.5pp）。此时 **MUST NOT 据此调大容差或落盘基线**——那是拿故障噪声当常态、粉饰门禁；应修复环境后重跑。要更紧的门禁：换更稳的模型，或用 `--gate --samples 3` 守均值（方差更小）后相应调低 `--tolerance`。
- **采样协议**：基线用 `--samples 3` 的均值（稳定参照，一次性成本）；门禁默认**单次跑 + 容差**（便宜、可频繁跑），偶发误报可重跑或临时 `--samples`。
- **退出码**：`0` 通过 / `1` 文件缺失（含 `--gate` 时缺基线）/ `2` 用例非法·无 key 降级·`--gate` 与 `--update-baseline` 互斥 / `3` 检测到回归。
- **诚实标注**：基线有、当前 N/A 的被守指标标「无法比对（skipped）」，不判对错。`槽位抽取完整率` 已接线（change `evals-wire-slot-completeness`）：`actual_slots` 从工具调用 args 还原（跨工具合并 / 哨兵 `未知`·`无` 不计 / 同名冲突 last-write-wins），用例标 `expected_slots`，指标采**存在性口径**（只看期望槽位键是否被抽出、不比精确值——因当前 agent 抽出的值是自由文本且 `start_time` 常算错日期，精确匹配会几乎恒 miss；存在性贴合「完整率/coverage」本义，与 `expected_tool_args` 的参数级精确比对口径分明）。该指标列入门禁、出真值即守——门禁**守 3 项**（意图 + 工具 F1 + 槽位完整率）。**稳定性（change `evals-stabilize-gate-three`）**：预约子 Agent 对单轮输入保守，**单条用例的工具触发是强非确定行为**（实测同一最齐全输入在不同跑次间 1/3～3/3 波动，无法靠改写单条做到恒触发）。故靠**数据集冗余**稳住——`cases.jsonl` 备有 8 条信息齐全的祈使式预约锚点（精确时间+项目+时长+点名技师），各标 `expected_slots`；单条触发率虽仅 ~0.27，但「某次跑 8 条全不触发」≈ `0.73^8`，叠加既有用例后单跑约 4%、`--samples 3`（聚合下 3 次任一非 N/A 即非 N/A）≈ `6e-5`。实测多次单跑 `--gate` 均 PASS、**实守 3 项**（槽位完整率触发时覆盖满格 ≈100%）。**诚实保留项**：冗余是**降低而非消除**回落——极端非确定下若某单跑 8 条恰好全不触发，槽位仍 N/A、按 skipped 处理、当次回落 2 项；报告末行如实给出当次实守项数，不夸大「绝对永不回落」。靠 `--samples` 多跑 + 容差进一步吸收抖动。**重定基线（人审批准）**：新增 8 条改变了评估集，旧基线（21 条）与新 29 条跑分 apples-to-oranges——工具 F1 因新锚点（如实标完整 3 工具、agent 常只触发 1～2 个）被拉低且加大抖动，单跑偶误报回归。故在新 29 条集 `--update-baseline --samples 3` 重定基线：工具 F1 `66.3%→53.8%`（如实反映新集难度，未 relabel 粉饰）、意图 `82.5%→85.1%`、**槽位 `100% ±0.0%`（3 次零方差）**；新集观测 CI 半宽意图 ±21.6pp / 工具 F1 ±6.1pp，`0.20` 容差仍覆盖 F1（意图偶发宽抖动靠重跑/`--samples` 兜底）。

## 在线评估闭环（改造 7）

把 §3 的「在线」那条腿接上：**生产对话 → 落 trace → 半自动甄别坏 case → 人审标注 → 回灌 `cases.jsonl`**，形成「线上发现问题 → 离线防住它」的回路。依赖改造 6（有门禁，回灌才有意义）。

```bash
# ① 扫描 trace 目录，甄别「疑似坏」候选 → 产出标注草稿（JSON 列表）
uv run python -m evals.triage scan --out drafts.json

# ②（人工）编辑 drafts.json：给每条候选填 expected_intent / expected_tools / expected_tool_args / expected_slots
#    —— 真值只来自人工，工具绝不自动伪造。

# ③ 去重后回灌进 cases.jsonl（带 source=online），并提示重定基线
uv run python -m evals.triage append --from drafts.json
```

- **trace 怎么来的**：生产入口 [../api/chat_handler.py](../api/chat_handler.py) 的主 `AgentLoop` 已接 `Tracer + FileSpanExporter`，真实对话的 span 落 `evals/traces/*.jsonl`（运行期产物，已 gitignore）。tracer 经 `build_delegate_tool(..., tracer=)` 透传子 Agent，故领域工具调用也采得到。
- **采样**：默认全量（`sample_rate=1.0`）；**命中失控信号的 trace 必留**（不受采样率影响）。采样率经 `EVAL_TRACE_SAMPLE_RATE` 环境变量调。错误优先逻辑见 [../harness/observability/sampling_exporter.py](../harness/observability/sampling_exporter.py)。
- **甄别信号**（客观、纯函数，见 [../harness/observability/trace_signals.py](../harness/observability/trace_signals.py)）：`guardrail_exhausted` / `spin_detected`（loop 的 error 事件）、`tool_failure`（工具异常被吞成「工具执行失败…」回灌）、`max_steps_reached`（末步仍调工具、未产终态回复）。triage 只产「候选 + 草稿」，**不自动判真值、不自动改用例集**。
- **回灌不自动重定基线**：`append` 完只打印提醒，`baseline.json` 不动——基线变更走人审，不绕过改造 6 门禁。

> ⚠️ **诚实边界**：本项目自我定位学习/面试，**无真实线上用户流量**。这里的「生产 trace」=开发/手动对话或回放输入跑出的 trace，机制（产→采→标→回灌）是真的，但「在线」是模拟。
> 另一项已知局限：C-lite 下子 Agent 各自开 root span（`trace_id` 不同），triage 按 `trace_id` 分组，故**子 Agent 内部的工具失败会作为「以被委派 task 为 input」的独立候选**出现，而非挂回原始用户输入。把子 trace 关联回父回合需要一个跨 loop 的 correlation id——属后续工作。
> 还有：`[ERROR]` 回复前缀是**遗留 `agents/` 路径**的产物，当前生产走的 harness `AgentLoop` 只产 `[REPLY]`（含兜底），故不在甄别信号内——不臆造不存在的信号。

## 后续（Phase 1+ 落地时）

- [x] Phase 1 结构化输出改造后，重跑本评估集，确认意图准确率不低于基线（此阶段分类器仍在，指标可比）。
- [x] Phase 2 工具层就绪后，把 `expected_tools` 纳入评分（工具调用准确率）。
- [x] Phase 3 ReAct loop 后，意图指标退场，改用端到端通过率（plan Phase 3 验收口径）。
- [x] 把"跑 evals"接入 `/phase` 的验证闸门（闸门 2）——改造 6 已落地：`phase.md` 闸门 2 跑 `--gate`，退出码 `3`（回归）阻断归档、`2`（无 key/降级）跳过、`1`（缺基线）警告。
