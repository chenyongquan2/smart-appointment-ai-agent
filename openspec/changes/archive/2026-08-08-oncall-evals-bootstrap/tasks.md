## 1. EvalProfile 声明层（纯重构，预约域行为必须等价）

- [x] 1.1 新建 `domains/eval_profile.py`：frozen dataclass `EvalProfile`，含 `labels: frozenset[str]`、`slot_key_map: Mapping[str, str]`、`gated_metrics: tuple[str, ...]`；只做结构性校验（`labels` / `gated_metrics` 非空、类型正确），语义校验留给 `evals/`（design D2）
- [x] 1.2 `domains/__init__.py`：`Domain` 加 `eval_profile: EvalProfile` 字段，更新 docstring 的「五样东西」表述为「评估数据与标注口径」
- [x] 1.3 `domains/appointment/__init__.py`：声明 `EvalProfile`，三项**照抄当前硬编码值**——5 类意图标签、6 项槽位映射（含 `technician_name → technician`）、`("工具调用-F1", "槽位抽取完整率")`
- [x] 1.4 `domains/oncall/__init__.py`：声明 `EvalProfile`——5 类标签（`log_triage` / `code_lookup` / `docs_lookup` / `reference_lookup` / `other`）、**空** `slot_key_map`、`("工具调用-F1", "工具调用-参数级F1")`
- [x] 1.5 加离线单测：两域装载后 `eval_profile` 内容正确；空 `labels` 或空 `gated_metrics` 构造时报错

## 2. 评估机制去域耦合（三处硬编码改读声明）

- [x] 2.1 `evals/run_evals.py`：删 `VALID_INTENTS` 常量，`load_cases` 改收一个标签集合参数（由调用方从 `load_domain().eval_profile` 取），非法标签仍报行号 + `SystemExit(2)`
- [x] 2.2 `evals/metrics.py`：`_slots_from_tool_calls` 改收 `slot_key_map` 参数，删 `_SLOT_ARG_KEYS` 常量；`slot_key_map` 为空时直接返回 `None`（语义=本域不度量，指标恒 N/A）
- [x] 2.3 `evals/metrics.py`：删全局 `GATED_METRICS` 常量，门禁比对改收被守指标集参数；保留 `_LATENCY_METRIC` 与分档说明性指标名常量（它们域无关）
- [x] 2.4 `evals/run_evals.py`：加 `gated_metrics` 语义校验——指标名必须在报告指标名全集中；`端到端延迟` / `回复质量通过率` / 分档说明性指标（召回率/精确率/序列正确率/完全匹配率）被声明为被守项时报错退出 2
- [x] 2.5 报告渲染：`slot_key_map` 为空的域，`槽位抽取完整率` 一行附「本域不度量该项」说明，与「本次未捕获」的 N/A 区分开
- [x] 2.6 更新 `tests/` 中断言全局 `GATED_METRICS` 的守护测试为「按域取」，断言内容不变；补一条测试：oncall profile 下被守项为 F1 + 参数级 F1 且不含槽位完整率
- [x] 2.7 跑 `uv run pytest` 全绿；在预约域下跑 `uv run python evals/run_evals.py --gate --limit 5` 冒烟，确认加载与被守项判定与改动前一致

## 3. oncall 用例集骨架（手写）

- [x] 3.1 建 `domains/oncall/evals/cases.jsonl` 头部注释块：说明标签口径 5 类、`expected_tool_args` 只标枚举/短字面量键、默认值与自由文本入参不标（design D4）
- [x] 3.2 写 `log_triage` 类用例（≥5 条 dev）：含 traceId、报错片段、告警时刻下钻三种形态；`vlog_query` 锚点一律给窄 `window` 措辞以控网关流量
- [x] 3.3 写 `code_lookup` 类用例（≥5 条 dev）：`locate_service_code` / `code_search` / `read_source` 各 ≥3 条唯一期望工具的锚点
- [x] 3.4 写 `docs_lookup` 类用例（≥5 条 dev）：MT4/MT5 各半，标 `expected_tool_args.platform`（必填枚举，精确可判）；**只写 Manager API 语义问题**，返回码问题按分诊表属 `load_reference`（design D6b）
- [x] 3.5 写 `reference_lookup` 类用例（≥5 条 dev）：四种 `ReferenceName` 分诊，标 `expected_tool_args.name`
- [x] 3.6 写 `other` 类用例（≥5 条 dev）：与值守排障无关的输入，期望**不调任何工具**
- [x] 3.7 写跨工具组合用例：三条链路（定位→检索→读取 / 服务档案→查日志 / 错误码分诊→文档兜底）各 ≥1 条，`expected_tools` 按整段累计；**不写「查日志→看源码」单轮链路**（系统提示明确「本轮不做源码分析」，见 design D6b）
- [x] 3.8 写 held-out 子集（≥10 条，标 `"split": "held-out"`）：覆盖 ≥3 类标签，服务名 / traceId / 错误码与 dev 不重复
- [x] 3.9 `uv run python evals/run_evals.py --limit 5` 冒烟：确认用例加载通过、真跑能采到 `actual_tools`

## 4. trace 回灌真实种子

- [x] 4.1 `uv run python -m evals.triage scan --out drafts.json` 扫现存 3 份真实 oncall trace
- [x] 4.2 人工填 `drafts.json` 的 `expected_tools` / `expected_tool_args`（真值只来自人工，不自动伪造）
- [x] 4.3 `uv run python -m evals.triage append --from drafts.json` 回灌，检查去重与 `source=online` 标记
- [x] 4.4 记录回灌后各类标签的实际条数，确认仍满足 spec 的规模与每类下限

## 5. 定基线与容差校准

- [x] 5.1 定基线前确认评估环境语料可用：`repos/` 与 git worktree、MT 文档库、日志网关连通（缺任一则本跑次不得落盘基线）
  - **实测结果（2026-08-08）**：`ocs4`/`ocs5` prd worktree ✅ ready；日志网关 ✅ 连通（冒烟 5 条真跑成功）；**MT 文档库 ✅ 已配置**（`.env` 的 `ONCALL_MT_DOCS_DIR` → `data/mt-docs/{mt4docs.db,mt5api.db}`，两平台检索实测有命中）；`mttools` prd ❌ `branch_not_found`（`repos/mt-tools/.git-mirror` 的 `refs/heads` 里没有 `MTTools/prd`，只有远端跟踪引用）——**仅 held-out 1 条用到，不影响 dev 基线**
  - 定基线可以进行。`mttools` 那条另行处理，不阻塞
- [x] 5.2 `AGENT_DOMAIN=oncall uv run python evals/run_evals.py --samples 3 --update-baseline`，记录 `工具调用-F1` 与 `工具调用-参数级F1` 的 95% t-CI 半宽
- [x] 5.3 按实测最差半宽定容差（design D8：取历次最差、不追最新一次），写进 README 并说明依据；若跑次出现 `APIConnectionError` / 网关 5xx 致大批 N/A，作废该跑次重来
- [x] 5.4 单跑 `--gate` 验证：连跑 3 次均 PASS 且报告如实标注实守 2 项；若参数级 F1 半宽大到容差失去意义，退路是只守 F1 并在 README 如实记录只守 1 项

## 6. 文档与收尾

- [x] 6.1 `evals/README.md` 新增值守域章节：标签口径、门禁守哪两项及为何不是槽位完整率、`expected_tool_args` 标注规则
- [x] 6.2 `evals/README.md` 标注**明确不覆盖**的两层（回复质量、任务成功率）及理由，不暗示已覆盖
- [x] 6.3 `evals/README.md` 加两域指标不可比的警告；更新「📁 数据在哪、机制在哪」一节以反映 `EvalProfile` 也随域走
- [x] 6.4 更新 `openspec/project.md` 或 `CLAUDE.md` 中涉及「评估数据随域走」的表述（如与新口径不符）
- [x] 6.5 `uv run pytest` 全绿；在 oncall 域下 `--gate` 退出码为 0
