## 1. 集归属加载支持（run_evals.py:load_cases）

- [x] 1.1 `load_cases` 识别每条用例可选 `split` 字段:值 MUST ∈ `{dev, held-out}`,缺省归 `dev`;非法值报行号 `SystemExit(2)`(与既有 `expected_intent` 白名单校验一致)。给每条 case dict 附 `split` 键。
- [x] 1.2 单测(`tests/test_eval_split.py`):标 `dev`/`held-out` 正确归类;缺省用例归 `dev`(向后兼容);非法 `split` 值报行号退出 2;既有单/多轮用例仍正常加载。

## 2. 运行器分集过滤与开关（run_evals.py）

- [x] 2.1 加 `--include-heldout` 与 `--heldout-only` 开关(互斥,双开报错);不带开关 = 只评 dev。新增纯函数 `_filter_by_split` 按开关过滤用例集:默认 dev、`--include-heldout` 全评、`--heldout-only` 只 held-out。
- [x] 2.2 `--update-baseline` 与 `--gate` 恒基于 **dev 子集**:新增纯函数 `_split_results` 把同序结果按 case 的 `split` 拆成 (dev, held-out),`report_to_baseline`/`aggregated_to_baseline`/`_finish` 只喂 dev 侧——held-out 物理上进不了 `baseline_dict`。`--heldout-only` 与 `--update-baseline`/`--gate` 同用在 main() 与 `run_baseline` 双重拦截(退出码 2)。
- [x] 2.3 报告分集呈现:dev 报告照常打印(数量取自 `report['total']`);非空 held-out 单独打印分隔节 + 「不参与门禁/基线」标注 + 用例数,单次跑与多采样两条路径均覆盖。
- [x] 2.4 单测(`tests/test_eval_split.py`,离线确定性,纯函数级):`_filter_by_split` 三种开关组合;`_split_results` 保序拆分 + 全 dev/全 held-out 边界;端到端链路测试证明 held-out 结果(即便全判错)不拉低经 `_split_results→build_report→report_to_baseline` 产出的基线(验证「即便 `--include-heldout` 也只基于 dev」的核心保证)。

## 3. 扩充 dev 子集补足每类下限（cases.jsonl）

- [x] 3.1 统计当前 dev 各类目分布(appointment 20/query 6/pay 3/statistics 3/other 3),查漏补足:pay/statistics/other 各新增 2 条(共 +6)使 dev **每类 ≥5、总 41 ≥40**;保持单轮形态,沿用既有句式风格。
- [x] 3.2 结构校验(真 provider 无关,`python -c` 直跑 `load_cases`+`_filter_by_split`):dev=41、每类 ≥5(20/6/5/5/5)、5 类全覆盖 ✓。

## 4. 新增 held-out 子集（cases.jsonl）

- [x] 4.1 另写 10 条 held-out 用例(标 `split: held-out`):appointment 3(祈使式锚点,技师名刘/黄/郑师傅,不与 dev 重复)+ query 2 + pay 2 + statistics 2 + other 1,覆盖全部 5 类(超过 ≥3 要求);表头注释补 `split` 字段口径。
- [x] 4.2 结构校验:held-out=10、覆盖 5 类 ✓。`--heldout-only --limit 3` 真跑冒烟:`dev=0 held-out=3`,分集报告打印「不参与门禁/基线」,exit 0,未触碰基线文件。校验 `--heldout-only` 与 `--gate`/`--include-heldout` 的互斥拦截均生效(exit 2)。

## 5. 验证与基线（闸门 2）

- [x] 5.1 `uv run pytest` 全绿（252 passed, 9 xfailed；含新增 13 个 `test_eval_split.py`）。
- [x] 5.2 人审批准后在**新 dev 集(41 条)** `--update-baseline --samples 3` 重定 `baseline.json`：意图 77.2% ±14.0% / 工具F1 55.9% ±4.7% / 槽位 91.7% ±35.9%（n=3；9 个非 N/A 指标，total_cases=41）。运行日志 `dev=41 held-out=0` 确认 held-out 未进基线。
- [x] 5.3 重定后 3 次 `--gate` 均 PASS、**实守 3 项**：单采样两次（意图 87.8%/80.5%、工具F1 54.1%/61.7%、槽位 75.0%/88.9%），`--include-heldout` 一次（dev 侧意图 78.0% = 门禁当前值，证门禁只基于 dev；held-out 意图仅 60.0% 但未触发回归、exit 0，证 held-out 不影响退出码；held-out 分集单独呈现并标「不参与门禁/基线」）。**诚实边界**：单采样下槽位 eligible 数小（n=1~9）、CI 宽（基线 ±35.9%），极端非确定下单跑仍可能罕见回落 2 项，沿用改造 8 数据集冗余 + `--samples`/容差吸收。

## 6. 文档同步

- [x] 6.1 `evals/README.md`:新增「dev / held-out 切分」章节(语义、`split` 字段、三种运行方式、门禁恒基于 dev + 物理隔离、本切片规模 41+10),用例格式区补 `split` 字段说明。
- [x] 6.2 `docs/agent-eval-fieldguide.md`:§4.2 held-out 行 ❌→✅(留出集机制);§12 速查表规模行(51 条)、held-out 行、CI 门禁行(去掉过期「未收尾」note、改为 dev 41 条基线已重定+门禁复核稳定)、轨迹/多轮行、一句话结论;§13 改造 8 补第三切片 + 改写「如果只做一件事」为系统级业务指标;全局清理残留「35 条」「未收尾/尚未确认」表述;§7 CI 锚定、Q7、生产级蓝图、文件地图同步。路线图 SVG(视觉图)留待后续统一刷新。
