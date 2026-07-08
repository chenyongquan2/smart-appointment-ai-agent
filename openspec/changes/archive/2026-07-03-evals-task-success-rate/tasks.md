## 1. 采集工具执行成败（evals/trace_collect.py）

- [x] 1.1 新增纯函数 `collect_tool_outcomes(spans, exclude) -> list[{name, ok}]`（`evals/trace_collect.py`）。**实现优化**：observation 事件 payload 自带 `name`（`tracer.add_observation(span, name, result)`），故**直接采集 observation 事件**比按位置配对 tool_call 更 robust——`ok = not str(result).startswith(TOOL_FAILURE_PREFIX)`（复用 `trace_signals.TOOL_FAILURE_PREFIX`），剔除 `delegate`，按 `(span.start, 事件序)` 排列。每次工具调用必产 observation（`_dispatch` 吞异常成失败 observation），故不存在「调了无回执」缺口。
- [x] 1.2 单测（`tests/test_eval_trace_collect.py` +6）：成功→ok=True；「工具执行失败…」→ok=False；跨 span 按 start 排序；delegate 剔除；只采 observation（忽略 tool_call/thought）；空。
- [x] 2.1 `CaptureResult` 增 `tool_outcomes`，`run_and_capture_multiturn` 跑完 `collect_tool_outcomes(spans)` 填入（与 `tool_calls` 同源同沙盒、跨所有轮次）。`run_and_capture` 薄封装不变。
- [x] 2.2 `_run_once` 把 `cap.tool_outcomes` 填进 `EvalResult.actual_tool_outcomes`（真跑失败/未跑保持 None → N/A），`case.get("expected_outcome")` 填进 `EvalResult.expected_outcome`。
- [x] 2.3 单测（`tests/test_eval_multiturn.py` +1）：`_run_once` 用注入 fake 采集验证两字段正确填充；既有采集单测仍绿。

## 3. 任务成功率指标（metrics.py）

- [x] 3.1 `EvalResult` 增 `expected_outcome: Optional[str]`、`actual_tool_outcomes: Optional[list[dict]]`。
- [x] 3.2 新增纯函数 `task_success_rate(results)`：eligible = `expected_outcome` 非空且 `actual_tool_outcomes is not None`；单条成功 = 存在 outcome `name==expected_outcome` 且 `ok`（同名多次任一成功即成功）；宏平均；N/A 附原因；note 标「离线完成度代理，非真实业务 KPI」。加入 `__all__`。
- [x] 3.3 进 `build_report`（槽位之后、延迟之前）；`aggregate_runs`/`report_to_baseline` 靠指标名自动纳入；`GATED_METRICS` 常量不含它（门禁天然不受影响，无需改门禁代码）。
- [x] 3.4 单测（新文件 `tests/test_eval_task_success.py`，8 个）：成功/失败(ok=False)/终态未调用/未标注→N/A/未捕获→N/A/同名任一成功/混合宏平均 2/3；断言不在 `GATED_METRICS` 且 `compare_to_baseline` 压根不比它、门禁 PASS。

## 4. 标注用例（cases.jsonl）

- [x] 4.1 脚本按确定规则补 `expected_outcome`（create_appointment 在 expected_tools → create_appointment；否则 search_knowledge 在 → search_knowledge），只改需加键的行、其余原样。共 29 条（appointment 21 + query 8；outcome：create_appointment 22 / search_knowledge 7——「先咨询后预约」多轮 intent=query 但终态=建单）。pay/statistics/other 无标注。表头注释补字段口径。
- [x] 4.2 结构校验（`python -c` 直跑）：所有 outcome ∈ {create_appointment, search_knowledge} 且均在各自 `expected_tools` 内（bad=[]）；pay/stat/other 无标注；dev 标注 24/41、held-out 5/10；dev/held-out 计数与 5 类覆盖不变。

## 5. 验证与基线（闸门 2）

- [x] 5.1 `uv run pytest` 全绿（266 passed, 9 xfailed；新增 test_eval_task_success.py 8 + trace_collect 6 + multiturn 1）。
- [x] 5.2 冒烟（真 provider，`--limit 6`）：任务成功率出现在报告 = `0.0% 0/5`，带「离线完成度代理」标注，exit 0。诚实观察：0% 符合 design 预期——agent 驱动到工具调用（意图/工具有分）但很少真正成功完成 create_appointment 终态（子 Agent 保守 + 强非确定 + 建单执行常失败）；这正是本指标暴露的、其他指标看不到的「办没办成」缺口。
- [x] 5.3 **人审决定省重定**（本 change 只新增非门禁指标 + 不改行为的注解，旧 dev 41 条基线对门禁仍有效，省 provider token）。故不 `--update-baseline`；`baseline.json` 不动，任务成功率不进基线。
- [x] 5.4 单次 `--gate`（dev 41）确认旧基线下门禁仍 **PASS、实守 3 项**（意图 68.3%→守、工具F1 53.7%→守、槽位 75.0%→守，均在容差内）；任务成功率 **20.8% 5/24** 出现在报告但**不在门禁裁决列**（非门禁、不影响退出码）。诚实观察：24 条期望达成业务终态、仅 5 条真正成功完成——这正是任务成功率暴露的、意图/工具指标看不到的「办没办成」缺口（强非确定，值会抖）。

## 6. 文档同步

- [x] 6.1 `evals/README.md`：新增「任务成功率」章节（口径=终态工具调用且未失败、collect_tool_outcomes 采集、v1 不纳门禁、离线代理诚实边界、实测 ~20%）；用例格式区补 `expected_outcome` 字段。
- [x] 6.2 `docs/agent-eval-fieldguide.md`：§12 系统级行 ❌→⚠️ 部分（任务成功率）；§2 卡在哪层锚点、一句话结论、§13「如果只做一件事」改为数据集规模化（系统级已有代理）、Q1 与诚实话术三处同步；清理多轮收尾等过期表述。（§5 未新增小节——系统级指标在 §2/§12 已充分锚定，避免过度编辑。）
