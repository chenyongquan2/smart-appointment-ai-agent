## Why

`evals/` 目前是「人工跑、人工看」——跑分结果只打印到终端，没有持久化基线、没有阈值阻断，所以**回归无法被自动拦住**。这正是 [agent-eval-fieldguide.md §8/§13 改造 6](../../../docs/agent-eval-fieldguide.md) 列为待办、也是 [CLAUDE.md](../../../CLAUDE.md) 「闸门 2 跑 evals 防回归」承诺尚未兑现的一环。改造 1+2 已让工具调用出真数，改造 3 给了 run-to-run 抖动的量化，门禁所需的「真实可比指标 + 噪声容差」前置条件均已就绪，现在做正当其时。

> **范围澄清（grilling 结论）**：本仓库**没有任何 CI 系统**（无 `.github/workflows`、无 pipeline 文件）。所以「CI 门禁」落地为**退出码契约 + 接进 [.claude/commands/phase.md](../../../.claude/commands/phase.md) 的人审/验证闸门 2**，而非接入某个 pipeline。门禁是「闸门 2 在有 key 时尽力跑」的纪律，不是硬性 CI 依赖。

## What Changes

- **基线持久化**：新增把一次跑分结果落盘为基线 JSON（`evals/baseline.json`）的能力，经 `--update-baseline` 显式写入；基线记录**全部非 N/A 指标**的值（完整快照，供历史/参照）+ 元信息（用例数、采样次数、schema 版本）。基线进 git、可追溯。
- **门禁只守精选正确性子集**：经 `--gate` 开启门禁——跑完后只对**显式常量 `GATED_METRICS = {意图分类准确率, 工具调用-F1, 槽位抽取完整率}`** 逐项比对基线；任一被守指标**回归超过容差**则以**新退出码 `3`** 结束。**`latency` 与 `response_quality` 排除在门禁外**（前者环境相关易抖、后者来自未校准 judge 不可当真值），仍照常打印、只是不阻断。工具调用 6 个子指标里**只守 F1**（name 级部分给分、平滑退化），其余仍打印不门禁。
- **容差有依据**：容差经 `--tolerance`（默认 `0.05`）吸收抖动；生成基线那步用 `--samples` 观测各指标 95% t-CI 半宽，确认 0.05 覆盖实测抖动（否则调高），把依据写进 README，而非留无凭据的魔数。比率型回归判定为 `当前 < 基线 − 容差`（被守的 3 个均为比率）。
- **采样协议**：基线用 `--samples 3` 的均值作稳定参照（一次性成本）；门禁默认**单次跑 + 容差**（便宜、可频繁跑），可临时 `--samples` 加稳。
- **诚实的门禁语义**：基线有、当前为 N/A（或反之）的指标 SHALL 标「无法比对（skipped）」而非判失败；当前新增、基线没有的指标仅作信息提示。**槽位完整率当前结构性恒 N/A**（`actual_slots` 未接线、无用例标 `expected_slots`），故虽列入门禁集，今天实际恒被跳过——门禁今天实守 2 个指标（意图 + 工具 F1），输出与 README 如实标注。比对逻辑实现为**纯函数**（吃当前报告 + 基线 → 门禁裁决），与 IO/退出码解耦，可离线确定性单测。
- **默认行为不变**：不带 `--gate`/`--update-baseline` 时，运行器行为与今天完全一致（打印报告、退出 0），门禁为**显式 opt-in**。
- **生成并提交首版基线**：实现期用 `.env` 的 key 真跑生成 `evals/baseline.json` 并提交，门禁立即可用。
- **接入验证闸门 2**：把 [phase.md:32](../../../.claude/commands/phase.md) 的 `uv run python evals/run_evals.py` 改为 `--gate`；只在退出码 `3`（回归）阻断归档，`2`（无 key/降级）跳过、`1`（缺基线）警告。落实 [README:62 的 TODO](../../../evals/README.md)。

## Capabilities

### New Capabilities
<!-- 无新增独立能力——门禁是评估能力的延伸 -->

### Modified Capabilities
- `eval-harness`: 新增「基线持久化 + 回归门禁」要求——运行器可把跑分落盘为基线（全部非 N/A 指标的快照）、可在门禁模式下只对精选正确性子集比对基线并对回归非零退出，比对为纯函数、容差吸收抖动、缺数据标「无法比对」而非伪造判失败。

## Impact

- **代码**：`evals/run_evals.py`（新增 `--gate`/`--update-baseline`/`--tolerance`/`--baseline` 参数、互斥校验与退出码 `3`）、`evals/metrics.py`（新增纯函数：报告/聚合↔基线序列化、`GATED_METRICS` 常量、`compare_to_baseline` 门禁裁决与渲染）、`tests/`（新增门禁纯函数的离线确定性单测）。
- **新增数据文件**：`evals/baseline.json`（首版基线实跑生成并进 git）。
- **流程接线**：`.claude/commands/phase.md`（闸门 2 改跑 `--gate`，按退出码语义阻断/跳过/警告）。
- **文档**：`evals/README.md`（基线/门禁用法 + 容差依据）、`docs/agent-eval-fieldguide.md`（§12 修正槽位「✅ 真评」的不准确表述为「未接线」；§12/§13 把 CI 门禁标为已落地）。
- **退出码契约**：在既有 `0/1/2` 之上新增 `3 = 检测到回归`，可区分「通过 / 文件缺失或缺基线 / 用例非法或无 key 降级 / 回归」。
- **不动**：分类器、AgentLoop、services/、judge、采样逻辑均不改；门禁纯属评估层的读后比对。
