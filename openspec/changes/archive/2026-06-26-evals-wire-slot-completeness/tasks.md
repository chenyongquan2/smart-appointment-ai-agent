## 1. 槽位还原纯函数（TDD）

- [x] 1.1 在 `tests/`（新建 `tests/test_slot_recovery.py` 或并入既有 evals 测试）先写失败单测：覆盖 ①跨工具合并（find_technician + create_appointment）②同名冲突 last-write-wins ③哨兵值 `未知`/`无` 不计入 ④空/None 工具调用返回 None ⑤`technician_name` 归一为 `technician`
- [x] 1.2 在 `evals/metrics.py` 实现纯函数 `slots_from_tool_calls(tool_calls) -> dict | None`：合并各工具 args 中的槽位字段、键归一到 `{start_time, duration, project, preference, gender, technician}`、跳过哨兵默认值、空/失败返回 None（不触网、确定性）
- [x] 1.3 定义哨兵常量集合（如 `_SLOT_SENTINELS = {"未知", "无"}`），加注释指向 `harness/tools/schemas.py` 的默认值，避免漂移
- [x] 1.4 跑 `uv run pytest tests/test_slot_recovery.py` 转绿

## 2. 运行器接线

- [x] 2.1 `evals/run_evals.py`：import `slots_from_tool_calls`，把 `actual_slots=None`（约 line 150）替换为从 `cap.tool_calls` 还原；真跑失败路径仍保持 `actual_slots=None`（标 N/A）
- [x] 2.2 确认 `_EvalResult.actual_slots` 流向 `slot_completeness` 无误（值真跑出非 N/A）

## 3. 用例标注 expected_slots

- [x] 3.1 给 `evals/cases.jsonl` 中若干代表性预约用例补标 `expected_slots`（只标用户输入里**明确给出**的槽位，宁缺毋滥）
- [x] 3.2 在 cases.jsonl 顶部注释区补一行 `expected_slots` 字段说明，并点明与 `expected_tool_args` 的口径区别（逐工具参数 vs 整轮跨工具槽位全集）

## 4. 报告措辞

- [x] 4.1 核对 run_evals.py 报告里「门禁今天实守 N 项」逻辑：接线后应自动显示 3 项（若数字为硬编码，改为按实际可比的 GATED 指标数动态计算）

## 5. 验证与基线（闸门 2）

- [x] 5.1 跑 `uv run pytest`（全量）确认无回归、新单测绿
- [x] 5.2 （需 API key）`uv run python evals/run_evals.py --samples 3 --update-baseline` 重定基线，确认 `baseline.json` 含 `槽位抽取完整率` 真值 — ✅ 槽位 100.0%±0.0%（n=3），基线含 9 个非 N/A 指标
- [x] 5.3 （需 API key）`uv run python evals/run_evals.py --gate` 确认门禁退出码 0、实守项数如实 — ✅ exit 0 PASS；本次单跑无标注用例触发工具→槽位 N/A→按 skipped（无法比对，不判失败），当次实守 2 项。验证了「最多 3 项、工具非确定性触发故单跑可回落 2 项」的文档承诺与 skipped 语义；基线（--samples 3）下槽位出真值 100%

## 6. 文档同步

- [x] 6.1 `evals/README.md`：更新「改造 6」段落里「实守 2 项 / 槽位结构性恒 N/A」的措辞为「实守 3 项 / 槽位已接线」
- [x] 6.2 `docs/agent-eval-fieldguide.md`：同步第 53 行、改造 6 段落等处的「实守 2 项」措辞；记录槽位接线为本次改造的兑现
