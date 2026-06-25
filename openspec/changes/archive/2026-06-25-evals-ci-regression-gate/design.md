## Context

`evals/metrics.py` 已把所有指标计算做成**纯函数**，`evals/run_evals.py` 负责触网跑分 + IO + 退出码。改造 6 的门禁要延续这条分界：**比对裁决是纯函数，读写基线 JSON 与设置退出码是 IO**。基线要吸收改造 3 量化的 run-to-run 抖动，故用「容差」而非精确相等。退出码已有约定 `0/1/2`（见 `run_evals.py` 与 README），需新增一个不冲突的回归码（已确认 `3` 在项目代码中未被占用）。

**grilling 结论（约束本设计）**：① 仓库无 CI 系统，门禁落地为退出码契约 + 接进 `.claude/commands/phase.md` 闸门 2；② 门禁只守精选正确性子集，不守 latency（环境噪声）与 response_quality（judge 未校准）；③ 工具调用只守 F1；④ 槽位完整率结构性恒 N/A（`actual_slots` 未接线 + 无用例标 `expected_slots`），列入门禁集但今天恒跳过，须如实标注；⑤ 容差 0.05 在基线生成时用 `--samples` 实测半宽校准；⑥ 基线用 samples=3 均值、门禁默认单次；⑦ 本改造实跑生成并提交首版基线。

## Goals / Non-Goals

**Goals**
- 一次跑分可落盘为基线 JSON（全部非 N/A 指标快照）；门禁模式下只对精选正确性子集比对基线、对回归非零退出。
- 比对纯函数化、可离线确定性单测；容差吸收抖动；缺数据标「无法比对」不伪造；恒跳过的指标如实标注。
- 默认行为零变化（门禁 opt-in）；单次/多采样都适用；接进 phase.md 闸门 2。

**Non-Goals**
- 不做 CI-aware 门禁（用半宽做动态容差）——本次用固定 `--tolerance`，CI-aware 留作后续。
- 不接真实 CI 系统（仓库本就没有）——只提供退出码契约 + 接入 `.claude/commands/phase.md` 闸门 2。
- 不在本改造接线槽位采集（`actual_slots`）或补 `expected_slots` 标注——那是独立工作；本次只把槽位列入门禁集并如实标注其恒跳过。
- 不做绝对阈值门禁——只做「相对基线 + 容差」；绝对阈值增加配置负担、留作后续。
- 不动分类器/loop/judge/采样逻辑；不引入新依赖（标准库 `json` 足够）。

## Decisions

### D1 · 基线 JSON 结构（全部非 N/A 指标的快照）
```json
{
  "schema_version": 1,
  "meta": {"total_cases": 20, "samples": 3},
  "metrics": {
    "意图分类准确率": {"value": 0.85, "is_latency": false},
    "工具调用-F1":   {"value": 0.72, "is_latency": false},
    "端到端延迟":    {"value": 1.234, "is_latency": true}
  }
}
```
- 基线存**全部非 N/A** 指标（完整快照，供历史与参照）；N/A 不可比、不写入（写进去等于伪造可比项）。门禁只在比对时取 `GATED_METRICS` 子集，与基线存什么解耦。
- `is_latency` 标志决定比对方向。键用指标 `name`（与 `Metric.name` 一致，跨改造稳定）。
- `schema_version` 预留：未来基线结构变化时门禁可拒绝/迁移旧基线。

### D2 · 门禁守的指标子集（显式常量）
`metrics.py` 定义常量 `GATED_METRICS = ("意图分类准确率", "工具调用-F1", "槽位抽取完整率")`——只守这三项正确性指标。**排除** latency（环境噪声、非正确性信号）与 response_quality（judge 未校准、不可当真值）；工具调用 6 个子指标里只守 F1（name 级部分给分、平滑退化，不像完全匹配率一个工具变动就跳）。其余指标基线照存、报告照打，但 `compare_to_baseline` 不据其判 pass/fail（至多作信息提示）。

> 注：`槽位抽取完整率` 当前结构性恒 N/A（`actual_slots` 未接线 + 无用例标 `expected_slots`），列入常量是前瞻——接上即自动生效；今天恒被标 skipped，门禁实守 2 项，报告须如实标注（见 D4 渲染）。

### D3 · 纯函数边界（放 `metrics.py`）
新增四个纯函数 + 一个常量，全部不触网、不读写文件：
- `GATED_METRICS`：门禁集常量（D2）。
- `report_to_baseline(report, *, total_cases, samples) -> dict`：单次报告 → 基线 dict（全部非 N/A）。
- `aggregated_to_baseline(aggregated, *, total_cases, samples) -> dict`：多采样聚合（`AggregatedMetric`，用 `mean`，跳过 `na`）→ 基线 dict。
- `compare_to_baseline(current, baseline, tolerance, *, gated=GATED_METRICS) -> GateReport`：核心裁决。`current` 为统一的 `{name: (value, is_latency)}` 视图（两种报告各自提取，`na` 项不入视图）。只遍历 `gated` 项产出 `GateVerdict{name, baseline, current, delta, status}`，`status ∈ {ok, regressed, skipped, new}`（基线有当前无→skipped；当前有基线无→new），整体 `passed = 无 regressed`。
- `format_gate_report(gate) -> str`：成功静默渲染——回归项详列基线/当前/差值、skipped 项注明原因、末行给「门禁实守 N 项指标、结论 PASS/FAIL」。

### D4 · 比对方向与容差
- 比率型：`regressed ⟺ current < baseline - tolerance`（被守 3 项均为比率）。
- 延迟型（`is_latency=True`）：`regressed ⟺ current > baseline + tolerance`——比对函数保留此方向以备将来，但当前 `GATED_METRICS` 不含延迟项。
- 容差默认经实测校准。**依据与结果**：生成基线那步（任务 4）用 `--samples 3` 观测各被守指标的 95% t-CI 半宽——实测意图准确率 ±19pp、工具 F1 ±7pp（n=3，当前 deepseek-v4-flash 结构化输出不稳放大了方差）。原拟默认 0.05 **不覆盖**实测抖动，故按本设计的「不覆盖则上调」规则把默认上调为 **0.20**（覆盖最差半宽），代价是只拦大幅回归；README 写明依据与 `--gate --samples` 收紧路径。

### D5 · 退出码与 CLI（`run_evals.py`）
退出码：新增 `3 = 检测到回归`，叠加既有 `0`（正常）/`1`（文件缺失/缺基线）/`2`（用例非法、无 key 降级、或 gate+update 互斥）。
- `--update-baseline`：跑完把结果写基线（`json.dump`，`ensure_ascii=False`），打印「已写基线」，返回 0。
- `--gate`：跑完读基线（缺失→提示先建基线、返回 1）→ `compare_to_baseline` + `format_gate_report`；回归返回 3、否则 0。
- `--baseline PATH`（默认 `evals/baseline.json`）、`--tolerance FLOAT`（默认 0.05）。
- `--gate` 与 `--update-baseline` 互斥（同时给→提示返回 2）——一次跑要么定基线要么守基线。
- 写/比对在 `run_baseline` 拿到单次 `report` 或多采样 `aggregated` 后进行，复用现有打印路径。无 key 路径不变（仍走清单 + 返回 2，门禁无从比对）。

### D6 · 与多采样兼容
基线默认由 `--samples 3` 生成 → 走 `aggregated_to_baseline`（记 `meta.samples=3`）。门禁默认单次 → 取 `Metric.value`（`na` 跳过）；`--samples N>1` 门禁则取各指标 `mean`。两条路径统一收敛到 `compare_to_baseline` 的 `{name: (value, is_latency)}` 视图。

## Risks / Trade-offs

- **固定容差 vs 抖动**：20 条小用例 + LLM 抖动下，5pp 容差可能仍偶发误报或漏报。缓解：基线生成时实测半宽校准容差（D4）；容差可调；README 说明依据；CI-aware（用改造 3 的半宽）留作后续，明确为 Non-Goal 而非遗漏。
- **门禁今天实守 2 项**：槽位恒 N/A，门禁只真正守住意图 + 工具 F1。缓解：报告/README 如实标注「实守 N 项」，不夸大；槽位列入常量待接线自动生效。这是诚实点而非缺陷。
- **基线易过期**：用例集/模型变化后基线需 `--update-baseline` 刷新。缓解：基线进 git，刷新即一次显式 commit，可审计；`schema_version` 兜底结构漂移。
- **门禁本身受非确定性影响**：单次门禁跑可能偶发误报。缓解：容差 + 可临时 `--samples` 加稳；误报时重跑成本低。

## Migration Plan

1. 先加 `metrics.py` 纯函数 + 常量 + 单测（不碰 run_evals，绿了再接）。
2. 接 `run_evals.py` 的 CLI 与 IO（读写 JSON、互斥校验、退出码）。
3. 用 `--samples 3 --update-baseline` 真实跑分生成首版 `evals/baseline.json`、顺便观测半宽校准容差，提交进 git。
4. 接线 `.claude/commands/phase.md:32` 闸门 2 改 `--gate`（按退出码语义阻断/跳过/警告）。
5. 文档：README 基线/门禁用法 + 容差依据；fieldguide §12 修正槽位表述、§12/§13 标 CI 门禁已落地。

## Open Questions

- （无）grilling 已逐项解决：门禁范围、工具子指标、槽位处理、容差依据、采样协议、闸门接法、首版基线生成。
