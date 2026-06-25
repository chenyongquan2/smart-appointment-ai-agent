# Tasks

## 1. metrics.py 纯函数（基线序列化 + 门禁裁决）

- [x] 1.1 新增常量 `GATED_METRICS = ("意图分类准确率", "工具调用-F1", "槽位抽取完整率")`——门禁只守这三项（排除 latency / response_quality / 其余工具子指标）。
- [x] 1.2 新增 `GateVerdict` 数据类（`name`、`baseline`、`current`、`delta`、`status ∈ {ok,regressed,skipped,new}`）与 `GateReport`（`verdicts: list`、`passed: bool`、`guarded_count: int`）。
- [x] 1.3 `report_to_baseline(report, *, total_cases, samples) -> dict`：单次报告 → 基线 dict（D1 结构），收**全部非 N/A** 指标，记 `value` + `is_latency`（延迟项值取秒）。
- [x] 1.4 `aggregated_to_baseline(aggregated, *, total_cases, samples) -> dict`：多采样 `AggregatedMetric` 列表 → 基线 dict（用 `mean`，跳过 `na`）。
- [x] 1.5 `compare_to_baseline(current, baseline, tolerance, *, gated=GATED_METRICS) -> GateReport`：只遍历 `gated`；比率回归 `当前<基线−容差`，延迟方向相反（保留备用）；基线有当前缺标 skipped、当前有基线缺标 new；整体 `passed = 无 regressed`，`guarded_count = 实际比对到的 ok/regressed 项数`。
- [x] 1.6 `format_gate_report(gate) -> str`：成功静默——回归项详列基线/当前/差值，skipped 项注明原因，末行「门禁实守 N 项，结论 PASS/FAIL」。
- [x] 1.7 把新符号（含 `GATED_METRICS`）加入 `__all__`。

## 2. tests：门禁纯函数离线确定性单测

- [x] 2.1 `report_to_baseline` / `aggregated_to_baseline`：收全部非 N/A、跳过 N/A、延迟项标 `is_latency`、元信息（含 samples）正确。
- [x] 2.2 `compare_to_baseline`：被守比率指标回归（<基线−容差）判 regressed；容差内不判回归；非门禁指标（latency/response_quality）即便变差也不进 verdict、不影响 `passed`。
- [x] 2.3 缺数据语义：基线有当前 N/A → skipped（不影响 passed）；当前有基线无 → new；槽位恒 N/A 场景下 `guarded_count` 如实为 2。
- [x] 2.4 `format_gate_report` 渲染含基线/当前/差值 + 「实守 N 项」末行，且通过项不刷屏（成功静默）。

## 3. run_evals.py：CLI 与 IO 接线

- [x] 3.1 新增参数 `--update-baseline`、`--gate`、`--baseline PATH`（默认 `evals/baseline.json`）、`--tolerance FLOAT`（默认 0.05）。
- [x] 3.2 互斥校验：`--gate` 与 `--update-baseline` 同时给 → 提示并返回 2。（已验证 exit=2）
- [x] 3.3 在 `run_baseline` 拿到单次 `report` / 多采样 `aggregated` 后：
  - `--update-baseline` → 调序列化纯函数写 JSON（`json.dump`，`ensure_ascii=False`，含 `schema_version`/`meta`），打印「已写基线」，返回 0。
  - `--gate` → 读基线 JSON（缺失则提示先建基线、返回 1），构造 `{name:(value,is_latency)}` 视图 → `compare_to_baseline` + `format_gate_report` 打印；回归返回 3、否则 0。
- [x] 3.4 退出码契约：文件 docstring/注释写明新增 `3 = 检测到回归`，`1` 兼含「缺基线」，`2` 兼含「gate+update 互斥」。
- [x] 3.5 无 key 优雅降级路径不受影响（门禁需先真跑出指标；无 key 仍走既有清单 + 返回 2）。

## 4. 生成并提交首版基线 + 校准容差（用 .env 的 key 真跑）

- [x] 4.1 跑 `uv run python evals/run_evals.py --samples 3 --update-baseline` 生成 `evals/baseline.json`（意图 86.7% / 工具F1 65% / 延迟 3.43s，8 个非 N/A 指标）。
- [x] 4.2 观测半宽：意图 ±19pp、工具F1 ±7pp（n=3）——默认 0.05 **不覆盖**，按规则上调 `--tolerance` 默认为 **0.20**（覆盖最差半宽），代码 + docstring + README 同步。
- [x] 4.3 核对基线数值合理（意图/F1 非 N/A、延迟为正、槽位/回复质量缺席合预期）；容差依据写入 README（5.1）。git 提交留待归档后统一处理。

## 5. 文档同步

- [x] 5.1 `evals/README.md`：新增「基线与回归门禁」小节（用法 `--update-baseline` / `--gate` / `--tolerance`；门禁守 `GATED_METRICS`、排除 latency/judge 的理由；退出码 `3`；容差 0.05 的实测依据；槽位今天恒跳过、实守 2 项的诚实说明），把 README:62「接入闸门 2」TODO 勾掉并写明 `--gate` 接法。
- [x] 5.2 `.claude/commands/phase.md`：闸门 2 的 `uv run python evals/run_evals.py` 改为 `--gate`，并注明退出码语义——`3`(回归) 阻断归档、`2`(无 key/降级) 跳过、`1`(缺基线) 警告。
- [x] 5.3 `docs/agent-eval-fieldguide.md`：§12 把「端到端·槽位抽取 ✅ 真评」修正为「未接线（actual_slots 恒 N/A、无用例标 expected_slots）」；§12 速查表把「CI 门禁（基线+阈值阻断）」从 ❌ TODO 改为 ✅（注明实守 2 项）；§13 改造 6 标记已落地。

## 6. 验证（闸门 2）

- [x] 6.1 `uv run pytest` 全绿（含新增门禁单测）。207 passed, 9 xfailed。
- [x] 6.2 自检全过：对夸大基线跑 `--gate --limit 3` 正确判回归→exit 3（含「实守 2 项」+ Δ 详情）；`--gate`/`--update-baseline` 互斥→exit 2；缺基线时 `--gate`→exit 1 且即时提示（不白跑）；默认不带旗标行为不变（_finish 返回 0）。
