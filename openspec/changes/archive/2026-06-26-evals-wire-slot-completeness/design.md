## Context

回归门禁（改造 6，archive `2026-06-25-evals-ci-regression-gate`）把 `槽位抽取完整率` 列进了 `GATED_METRICS`，但它今天**结构性恒 N/A**：

- `evals/run_evals.py:150` 硬写 `actual_slots=None`；
- `evals/cases.jsonl` 无用例标 `expected_slots`。

而下游早已就位：`slot_completeness`（`evals/metrics.py:293`）算法完整（宏平均：逐用例「命中数/期望槽位数」再跨用例平均，缺字段标 N/A）；端到端真跑（`evals/agent_capture.py` 的 `run_and_capture`）已把工具调用序列 `[{name, args}]` 采进 `CaptureResult.tool_calls`。槽位字段就藏在这些 args 里——`harness/tools/schemas.py` 定义了 `find_technician`（start_time/duration/project/preference/gender/technician_name）、`create_appointment`（start_time/duration/project/technician_id/session_id）、`check_availability`（start_time/duration）。

缺的只是「把 args 还原成扁平槽位 dict」这一步纯函数 + 给用例补标。

## Goals / Non-Goals

**Goals:**
- 让 `slot_completeness` 跑出真值（非 N/A），门禁实守项数报告由 2 → 3。
- 还原逻辑为纯函数、确定性单测（对齐 `tests/test_eval_gate.py` 的离线测试惯例）。
- 文档（README、fieldguide）措辞如实同步，不夸大、不再说「恒 N/A」。

**Non-Goals:**
- 不改 `slot_completeness` 算法本身、不改门禁比对逻辑、不改 `GATED_METRICS` 集合。
- 不改 `harness/` 生产路径（槽位仍来自工具 args，不新增「槽位抽取」专用工具）。
- 不追求 cases.jsonl 全量标 `expected_slots`——只标若干代表性预约用例足以让指标出真数（数据集扩充是改造 8 的事）。
- 不接外部 RAG（改造 5 暂缓）。

## Decisions

### D1 · `actual_slots` 从工具 args 还原，而非新增采集通道
**选择**：复用已采集的 `CaptureResult.tool_calls`，写一个纯函数 `slots_from_tool_calls(tool_calls) -> dict | None` 把各工具 args 中的槽位字段合并。
**为什么**：槽位在 harness 路径里本就是工具调用参数（Phase 1 的 `AppointmentSlots` 语义已沉淀进工具 schema）；无需在 loop 里再加旁路采集。**否决**「在 agent_capture 里单独抓 InputParser 输出」——生产主 loop 经 delegate→子 Agent，InputParser 不在统一可见面上，且会引入与工具 args 不一致的第二份真相源。

### D2 · 落点放 `evals/metrics.py`（与 slot_completeness 同模块）
**选择**：纯函数放 `evals/metrics.py`，紧邻 `slot_completeness`；`run_evals.py` import 后在 `actual_slots=` 处调用。
**为什么**：metrics.py 已是「纯函数 + 可离线单测」的归属地（`compare_to_baseline` 在此）；run_evals.py 是 IO/编排层，保持薄。**备选**新建 `evals/slots.py`——当前函数体量小（一个 dict 合并），单独成文件收益不抵碎片化成本；若日后槽位逻辑膨胀再拆。

### D3 · 键归一口径：`technician_name` → `technician`，其余同名
**选择**：统一槽位键为 `{start_time, duration, project, preference, gender, technician}`。工具 schema 里叫 `technician_name`，归一为 `technician`（对齐 README「意图口径」与 Phase 1 `AppointmentSlots` 的 `technician` 命名）。`create_appointment` 的 `technician_id`/`session_id` **不**是抽取槽位（前者是 find 之后拿到的 ID、后者是会话基建），不纳入。
**为什么**：槽位指标度量的是「模型从用户话里抽对了几个语义槽」，ID/session 不是用户表达的槽位。

### D4 · 同名冲突：last-write-wins（按 tool_calls 顺序）
**选择**：合并时后出现的工具调用覆盖先出现的同名槽位。
**为什么**：确定性（不依赖 dict 遍历顺序），且语义合理——`create_appointment` 通常在 `find_technician` 之后，承载最终确认的槽位值。冲突在实践中罕见（多为同值），选一个确定规则即可，避免「取并集导致一键多值」的复杂度。

### D5 · 哨兵值（`未知`/`无`）视为「未抽取」，不写入 actual_slots
**选择**：工具 schema 的可选槽位默认占位串 `未知`/`无`（见 schemas.py:39-45）在还原时**跳过**，不计入 `actual_slots`。
**为什么**：这些是「模型没填，工具兜底的默认值」，不是模型真抽到的槽位。若计入，完整率会被默认值虚高（违背诚实原则）。哨兵集合 `{"未知", "无"}` 作显式常量，与 schema 默认值对齐。

### D6 · `expected_slots` 独立标注，不从 `expected_tool_args` 派生
**选择**：cases.jsonl 新增独立的 `expected_slots` 字段，**手工标注**，不程序化从 `expected_tool_args` 推导。
**为什么**：二者口径不同——`expected_tool_args` 是**逐工具**参数稳定键（喂参数级 P/R/F1，按工具拆分、改造 2），`expected_slots` 是**整轮跨工具**应抽到的槽位全集（喂宏平均完整率、门禁守的那个）。强行派生会把口径差异藏起来、让两个指标耦合。**代价**：少量双重标注；可接受（只标若干用例），且独立标注反而能交叉印证。design 在 specs 里以两条 requirement 把口径写死。

### D7 · 接线后必须重定基线
`slot_completeness` 由 N/A 变真值后，旧 `baseline.json` 无该项。需 `--samples 3 --update-baseline` 重定基线纳入快照（一次性）。门禁守新指标的前提是基线里有它。

### D8 · 指标语义：**存在性完整率**，而非精确值匹配（实现中实测后修订）
**背景（实测证据）**：接线后用真 LLM 跑发现两个根因——① 预约子 Agent 对单轮输入**保守**，多数时候回复追问而非调 `find_technician`/`create_appointment`（实测全特化输入也仅 ~1/3 触发工具）；② 工具真触发时，槽位**值是自由文本**且不规范：`gender='男'`（非 `male`）、`project='中式推拿'`（非 `推拿`）、`start_time='2025-04-17'`（**模型算错日期**）。原 `slot_completeness` 用**精确值匹配** `actual.get(k)==v`，在此 agent 下几乎全 miss、`start_time` 永不命中——指标无法稳定出有意义的真数。

**选择**：把 `slot_completeness` 改为**存在性完整率**——期望槽位中「被抽出（键存在且非哨兵值）」的比例，**不比精确值**。`expected_slots` 由「期望键→期望值」重解释为**「期望被抽到的槽位键集合」**（仍写成 dict，值仅作人类可读说明、不参与判定）。
**为什么**：① 贴合指标名「完整**率**/coverage」——度量「抽没抽到」而非「抽得对不对」（后者是 `expected_tool_args` 的参数级 P/R/F1 的活，口径不重叠、各司其职）；② 绕开自由文本值与算错日期的噪声；③ 哨兵值已在 `slots_from_tool_calls`（D5）剔除，故「键存在于 `actual_slots`」天然等价于「抽到了非默认的真实值」。
**代价/残留**：工具非确定性触发（~1/3）仍在——某次跑若相关用例都没触发工具，该指标 N/A（按既有 skipped 语义处理）；靠 `--samples` + 容差吸收。这点 README/fieldguide 如实标注，不夸大为「稳定守住」。
**否决**「保留精确匹配、按模型中文实际值标注」——overfit 到单一模型的措辞、与 `expected_tool_args` 的 `male/推拿` 口径冲突、且 `start_time` 算错日期无解，最不稳。

## Risks / Trade-offs

- **[槽位真值波动大]** → 当前模型 `deepseek-v4-flash` 结构化输出不稳（README 实测意图 ±19pp）。槽位完整率可能抖动更大。**缓解**：基线用 `--samples 3` 均值；门禁默认容差 0.20 已为吸收抖动校准；接线后观察实测半宽，必要时在 README 记录槽位的容差依据。
- **[`expected_slots` 标注主观]** → 「哪些槽位算期望」有判断空间。**缓解**：只标用户输入里**明确给出**的槽位（如「男技师」→ gender、「推拿」→ project、「明天下午两点」→ start_time）；模糊的不标，宁缺毋滥，避免把指标变成噪声。
- **[哨兵集合与 schema 默认值漂移]** → 若日后改 schema 默认占位串而忘了同步还原函数的哨兵集合，会误判。**缓解**：哨兵常量加注释指向 `schemas.py`；单测覆盖「默认值不计入」一例，schema 改动会让该测失败暴露。
- **[只标少量用例 → 指标统计意义弱]** → 接线初期 expected_slots 用例数少，完整率方差大。**缓解**：诚实——这是改造 8（数据集扩充）的范畴；本变更只负责「让指标从 N/A 变真数、门禁实守 3 项」，不承诺统计强度，文档如实标注。

## Migration Plan

1. 实现 `slots_from_tool_calls` 纯函数 + 单测（红→绿）。
2. `run_evals.py` 接线 `actual_slots`。
3. cases.jsonl 补标若干 `expected_slots`。
4. 跑 `uv run pytest`（闸门 2 的单测部分）确认绿。
5. `uv run python evals/run_evals.py --samples 3 --update-baseline` 重定基线（需 API key）。
6. 同步 README / fieldguide 措辞（实守 2 → 3、删「结构性恒 N/A」）。

**回滚**：还原 `actual_slots=None`、撤 cases 标注、恢复旧 baseline.json 即回到接线前；纯函数与单测可保留（无副作用）。

## Open Questions

- 槽位真值的容差是否需与意图/工具 F1 不同？→ 留待接线后实测半宽再定，初期沿用全局 `--tolerance 0.20`，README 记录观测值。
