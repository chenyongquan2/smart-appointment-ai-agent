# evals/ — 重构回归评估集（Phase 0）

> 开发期 harness 的**验证回路**核心。用例集贯穿整个重构;**评分指标随阶段演进**(见下方 ⚠️)。
> 配套：[../docs/harness-refactor-plan.md](../docs/harness-refactor-plan.md) 的 Phase 0。

> ⚠️ **用例集长期复用，但"评分指标"随阶段演进——别把意图准确率当永久指标。**
> - **Phase 1–2（分类器仍在）**：意图分类准确率是**有效的退化对照**(Phase 1 结构化输出正是要改进它,验收口径就是分类错误率)。
> - **Phase 3 ReAct/TAO 起**：意图分类并入 loop(意图隐含在"调了哪些工具"里)，评分改用**工具调用准确率 → 端到端结果（约对没约对）**(见 `expected_tools`；plan 的 Phase 3 验收口径也是"端到端通过率≥基线")。
> 耐用资产是**这批行为级用例 + 运行器框架**(与实现解耦)，而非某个准确率数字本身。

## 这是什么

一套**可复用的行为评估用例集 + 运行框架**——以 `输入 → 期望行为` 为用例，在把 `agents/` 重构为 `harness/` 的过程中**客观衡量**系统行为有没有退化，而不是靠"感觉还行"。用例集是**耐用资产**；评分模式随阶段演进（见上方 ⚠️）。

## 意图口径（5 类）

`expected_intent` 取自真实分类器 [../agents/task_classification/task_classifier.py](../agents/task_classification/task_classifier.py) 的输出空间：

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

## 运行

```bash
uv run python evals/run_evals.py            # 全量, 输出意图准确率基线
uv run python evals/run_evals.py --limit 5  # 冒烟, 只跑前 5 条
```

- 产出基线需 **API key 可用**（`.env` 里配好 `MODEL_PROVIDER` 对应的 `*_API_KEY`）。
- 无 key 时运行器**优雅降级**：打印用例清单 + 提示，并以非零码退出，不崩。

## 关于意图准确率（当前评分模式）

- 它是**一次性运行记录、非永久"基线"**，且**非确定性**（LLM 有随机性，即便 temperature=0 也可能微抖）。需要稳定对照时再考虑多次平均。
- 当前分类器用 `strip().lower()` + 白名单兜底，异常时降级为 `other`——这个数字会如实反映其表现，**正是 Phase 1（结构化输出）要改进的对象**。

## 基线与回归门禁（改造 6）

把"人工跑人工看"升级为"自动拦不达标"。两条命令：

```bash
# 定基线：把本次跑分落盘为基线（建议配 --samples 3 取稳定均值）
uv run python evals/run_evals.py --samples 3 --update-baseline

# 守基线：跑完比对基线，被守指标回归则以退出码 3 结束
uv run python evals/run_evals.py --gate
```

- **基线文件**：`evals/baseline.json`（进 git、可追溯），记录**全部非 N/A 指标**的快照 + 元信息（用例数、采样次数、`schema_version`）。可经 `--baseline <path>` 改路径。
- **门禁只守正确性子集** `GATED_METRICS = {意图分类准确率, 工具调用-F1, 槽位抽取完整率}`。**刻意排除**：
  - `端到端延迟`——机器/网络/API 负载相关，跨环境抖动大，非正确性信号；
  - `回复质量通过率`——来自**未校准** judge，按项目诚实原则不可当真值；
  - 工具调用的其余 5 个子指标——同一底层行为，只守 F1（name 级部分给分、平滑退化）即可。
  其余指标仍照常打印，只是不触发非零退出。
- **容差** `--tolerance`（默认 `0.20`）：比率即百分点（20pp），吸收 LLM 的 run-to-run 抖动。比率回归判定为 `当前 < 基线 − 容差`。**0.20 的依据（实测校准、非魔数）**：生成基线时观测被守指标的 95% t-CI 半宽（改造 3）——当前模型 `deepseek-v4-flash` 结构化输出不稳，**意图准确率 ±19pp、工具 F1 ±7pp（n=3）**。默认容差取 0.20 以覆盖最差半宽，单次门禁跑不会被噪声误报；**代价是只拦得住「大幅回归」**（如分类器/工具链整体崩坏）。要更紧的门禁：换更稳的模型，或用 `--gate --samples 3` 守均值（方差更小）后相应调低 `--tolerance`。
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
