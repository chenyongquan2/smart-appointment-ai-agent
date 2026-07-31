## Context

评测机制层已建齐（改造 1–4、6、7 + 改造 8 三切片），当前 `evals/cases.jsonl` 有效用例约 51 条：dev 41（每类 ≥5）+ held-out 10。多采样已用 mean±95% t-CI，但每类样本太少 → CI 宽、门禁在强非确定的工具触发上易误报、held-out 防过拟合信号弱。运行器/指标/采集代码（`run_evals.py` / `metrics.py` / `agent_capture.py`）与 split/schema 机制均已就绪，本切片**只喂数据 + 标注 + 重定基线**，不动机制。

## Goals / Non-Goals

**Goals:**
- dev 每类意图从 ≥5 抬到 **≥30**（5 类全达标）。
- held-out 从 10 扩到 **≥30**，覆盖 5 类。
- 扩容含若干多轮 `turns` 用例（预约逐步给槽/澄清/改约），补厚轨迹级样本。
- 有业务终态的新用例补 `expected_outcome`，扩大任务成功率有效分母。
- 数据集变更后在 dev 上 `--samples 3` 重定 `baseline.json`，人审。
- 同步 `evals/README.md` 与 `docs/agent-eval-fieldguide.md`。

**Non-Goals:**
- 不引入新指标、不改评分口径、不改运行器/指标/采集代码（除非扩容中发现 split/schema 处理缺陷，最小修补）。
- 不追求「几百条」一步到位——本切片把每类下限从 5 抬到 30 作为可交付第一台阶。
- 不碰真实流量、真实业务 KPI（属 L3）。
- 禁改 `services/` / `harness/runtime` / 子 Agent 提示。

## Decisions

- **规模台阶定为「每类 30 / held-out 30」**：足以显著收窄 CI、又不至于一次性堆到几百条使本切片失控；「几百条」留后续切片继续投入（属持续投入型）。
- **多样性优先于数量**：扩容用例按「措辞变体 / 边界 / 含噪声 / 多槽位组合」维度设计，避免机械复制同句式凑数（近似重复不计入下限）——否则样本增多但信息量不增，CI 不会真收窄。
- **held-out 保持真·留出**：held-out 用例只做过拟合体检，不参与任何 prompt/阈值/用例调优，沿用既有 `_split_results` 物理隔离，不进 baseline、不触发门禁退出码。
- **outcome 标注只标有工具终态的类**：`appointment`→`create_appointment`、`query`→`search_knowledge`；`pay`/`statistics`/`other` 当前无工具终态，保持 N/A，不伪造分母（沿用 task-success 切片范式）。
- **重定基线走既有闸门**：数据集变更属会改门禁判定的行为变更（见记忆 `eval-trigger-nondeterminism`），必须 `--samples 3` 重定并人审，不能沿用旧基线。
- **分类靠脚本自检**：扩容后用一段一次性统计（每类计数 / split 分布 / schema 合法性）自查是否达标，纳入 tasks 验证步骤，避免「以为够了实际某类没到 30」。

## 现状盘点结果（回填，tasks 1.1/1.2）

实测 `evals/cases.jsonl`（2026-07-30，共 51 条，无非法行）：

| 类别 | dev 现状 | 距 30 | held-out |
|---|---|---|---|
| appointment | 20 | +10 | 3 |
| query | 6 | +24 | 2 |
| pay | 5 | +25 | 2 |
| statistics | 5 | +25 | 2 |
| other | 5 | +25 | 1 |
| **合计** | **41** | **+109** | 10（+20） |

另：29 条带 `expected_outcome`（22 `create_appointment` + 7 `search_knowledge`）、6 条多轮（均 2 轮）。

**关键发现：现有稳定性是靠冗余买来的。** appointment 的 20 条里 **10 条（50%）是同一个模板**——「我要预约{时间}做{时长}{项目}，要{力度}{性别}技师{姓名}，帮我订好」。这是 `evals-stabilize-gate-three` 为稳定门禁而加的祈使式锚点（见记忆 `eval-trigger-nondeterminism`：稳定性靠数据集冗余）。

由此**把 Risks 里「数字可能波动/下探」这条预测收紧**：走多样性路线后指标不是"可能波动"，而是**很可能真降**——因为被替换掉的正是那批人为压低方差的同款样本，而新增的是它们测不到的难例。`工具调用-F1` 从 56% 落到 40–45% 区间属正常，验收判据仍是「CI 收窄 + 分布合理」，绝不是追旧数字。这条预期必须在重定基线前对齐，否则会被误判成回归。

**各意图的标注约定（实测归纳，新增用例须遵循）**：

| 意图 | `expected_tools` | `expected_outcome` | `expected_slots` |
|---|---|---|---|
| appointment | `[find_technician, check_availability, create_appointment]`（信息不全时可为子集） | `create_appointment` | 有 |
| query | `[search_knowledge]`（问技师时加 `find_technician`） | `search_knowledge` | 一般无 |
| pay / statistics / other | `[]` | 无 | 无 |

`pay`/`statistics`/`other` 的 `expected_tools` 为空**不是缺标注**——它们测的正是「不该调工具时别乱调」，是负样本。

## Risks / Trade-offs

- **人工造数成本高**：30×5 + 30 held-out ≈ 180 条，多为手写。缓解：按意图类分批、复用现有句式骨架再做变体，但严格避免近似重复冒充。
- **重定基线后数字可能波动/下探**：样本变多后意图/工具F1/槽位的点估计可能变化（更接近真实、CI 更窄）。这是预期的「测得更准」，不是回归——人审时以「CI 收窄 + 分布合理」为验收，而非追旧数字。
- **强非确定项污染**：工具触发本身非确定，样本增多不会消除但会平均化其噪声；任务成功率仍不纳入门禁（沿用现状）。
- **多轮用例采集脆弱**：`turns` 驱动累积 history 的采集路径较新，扩容可能暴露既有边角 bug —— 若命中则最小修补运行器，并在 tasks 记录。
