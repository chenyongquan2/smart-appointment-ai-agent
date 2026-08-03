## 1. Tool 声明宽度类参数（先做——后面两处都依赖它）

- [x] 1.1 `harness/tools/base.py` 的 `Tool` 新增宽度类参数声明字段（缺省空集/空 frozenset → 行为与引入前完全一致）。docstring 里写明它是什么（只影响检索范围、不改变"在找什么"的旋钮）、**为何声明在 `Tool` 上而非运行时全局集合**（一个工具的宽度旋钮可能是另一个工具的身份维度；与 `Tool.timeout` 拒绝全局常量同源，design D3）。
- [x] 1.2 加测试：未声明的工具其宽度类参数为空集，且既有工具行为不变。

## 2. 记录时提取身份参数

- [x] 2.1 `harness/observability/tracer.py` 的 `add_tool_call` 接受可选的身份参数并写进 event payload（缺省不传时 payload 与现在一致，向后兼容）。
- [x] 2.2 `harness/runtime/agent_loop.py` 记录 `tool_call` 时查 `self.registry` 取该工具的宽度类参数声明，算出身份参数子集传给 tracer。**查表失败（如模型幻觉工具名）MUST 退化为「全部参数皆身份」且不得抛**——埋点不能拖垮主流程（沿用 `_extract_error_kind` 与 `end_span` 的同一取舍，design D2）。
- [x] 2.3 ⚠ 加测试钉住**判定侧零参数名硬编码**：扫 `harness/observability/trace_signals.py` 的真实代码（用 AST 而非扫源码字符串——扫字符串会被 docstring 误伤，见 `tests/test_tool_outcome.py` 同款教训），断言其中不出现 `window` / `limit` / `top_k` 这类具体参数名字面量。这条守的是「域内容不泄漏进域无关运行时」，不是可选项。
- [x] 2.4 加测试：声明了宽度类参数的工具，其 `tool_call` 事件的身份参数含检索词、不含时间窗；未声明的工具身份参数等于全部参数。

## 3. 新增信号（规则 D）

- [x] 3.1 `harness/observability/trace_signals.py` 新增信号：同一 `(工具名, 身份参数)` 组合累计出现的**步骤数** ≥ 阈值（缺省 3）即命中。**按步骤去重计数**（同一步内并行调多次同一工具只计 1，否则「多意图并行检索」直接变误报）；**不要求连续**（真实病态模式中间会夹 `load_reference`）。阈值可配（design D1、Open Question 2）。
- [x] 3.2 信号命名避免泛化的 "spin" 字样，与护栏产生的 `spin_detected` 明确区分——否则读者会以为护栏拦住了（design Open Question 1）。
- [x] 3.3 确认该信号自动进入 `is_bad_trace` → `SamplingSpanExporter` 必留 + triage 候选 + 信号计数摘要（既有机制，不需改）；加一条测试证明低采样率下仅命中本信号的 trace 仍必留。

## 4. 域侧声明

- [x] 4.1 `domains/oncall/tools/vlog.py` 的 `vlog_query` 声明 `window` / `limit` 为宽度类参数。
- [x] 4.2 预约域 `search_knowledge` 声明 `top_k` 为宽度类参数。
- [x] 4.3 复核其余工具是否需要声明——**不确定的就不声明**（缺省空集是安全侧：全部参数计入身份 → 信号更保守、不误报）。

## 5. 用真实形状做回归（本 change 的验收核心）

> ⚠ span MUST 合成：那 7 条真实 trace 含真实 requestId 与同事原话，trace 目录 gitignore 但**测试进版本库**——与「回灌 `cases.jsonl` 不得带 `user_id`」同一个道理（design D6）。保留形状、换掉标识值。

- [x] 5.1 病态①：同工具三步、检索词固定、时间窗 2d→30m→7d（真实坏 case 的形状，含**一步内两个调用**那个细节）→ MUST 命中。
- [x] 5.2 病态②：同工具四步、检索词固定、时间窗 6h→30m→12h → MUST 命中。
- [x] 5.3 ★ 正当①**逐维度枚举**：检索词与时间窗固定、环境逐个变（prod→uat→stg→dev）→ **MUST NOT 命中**。这是规则 D 相对 B/B'（误报 3 与 2）的全部价值所在；它一旦回归，这个信号就退化成噪声源。
- [x] 5.4 正当②换检索策略：先正则式查询、后精确词查询并收窄窗 → MUST NOT 命中。
- [x] 5.5 正当③多意图并行检索：同一步内针对不同检索词并行调同一工具 → MUST NOT 命中（验证「按步骤去重计数」这条口径）。
- [x] 5.6 不连续也命中：同身份出现在第 1、3、5 步、中间夹其它工具 → MUST 命中。
- [x] 5.7 阈值边界：同身份只出现 2 步 → MUST NOT 命中。

## 6. 验证与收尾

- [x] 6.1 `uv run pytest` 全绿——成功静默、只报错。
- [x] 6.2 ⚠ **确认循环行为零变化**：加/复核一条测试证明命中该信号**不会**使循环提前终止（护栏 `SpinDetector` 未被改动）。人审拍定的范围就是这条，实现里最容易越界的也是这条。
- [x] 6.3 对盘上已有的 6 个 trace 文件跑一次 `triage scan`，确认**候选数与内容相比本 change 前没有变化**——预期如此（老 payload 无身份参数字段，信号不会命中）。若变了说明实现走了硬编码回退，MUST 回到 2.3 复查。
- [x] 6.4 如实记录 design D5 的诚实边界：**规则对比表里的「2/3 命中」是离线用完整 args 复算出来的，不是老 trace 真能报出来**；覆盖自本 change 之后落的新 trace 起生效。写进本文件末节。
- [x] 6.5 如实记录 design 的两条非目标：**改写漂移未覆盖**（同工具反复改写检索键、多步无进展）、**护栏仍然拦不住**（3 分钟白等还会发生，本 change 只让它可见可计数）。收尾结论 MUST NOT 说成"打转问题解决了"。
- [x] 6.6 确认**不需要**重定 `evals/baseline.json`——本 change 不改评分指标、不改运行时行为（预约域评测冻结）。
- [x] 6.7 更新记忆 `spin-detector-args-blindspot`：观测侧已解决、护栏侧仍未解决，并写下"再谈护栏"的触发条件（攒够多少数据 / 误报率如何）。

---

## 收尾结论（2026-08-03）

### 做到了什么

`repeated_tool_identity` 信号已就位：同一 `(工具, 身份参数)` 组合出现在 ≥3 个步骤即命中；
身份参数 = 原始参数剔除 `Tool.breadth_args` 声明的宽度旋钮，由 `AgentLoop` 在**记录时**算好。
`vlog_query` 声明 `window`/`limit`，`search_knowledge` 声明 `top_k`。

测试 **625 passed / 1 skipped**（本 change 前 608，新增 17 条）。17 条里最要紧的两条：

- `test_legitimate_per_tenant_enumeration_not_flagged`——逐租户枚举 MUST NOT 命中。
  这是规则 D 相对 B/B'（误报 3 与 2）的全部价值；它一旦回归，信号就退化成噪声源。
- `test_signals_module_has_no_hardcoded_arg_names`——用 AST 断言判定模块里没有
  `window`/`limit`/`top_k`/`term`/`env` 这类参数名字面量，守「域内容不泄漏进域无关运行时」。

**真实 trace 复核（task 6.3）**：对盘上 6 个文件重跑 `triage scan`，候选与信号**逐条完全一致**
（3 条、全 `tool_timeout`）。这正是预期——老 payload 没有身份参数字段，本信号不会命中。
若这里变了，说明实现偷偷走了硬编码回退。

### ⚠ 三条诚实边界（勿在别处含糊掉）

1. **护栏仍然拦不住——那 3 分钟白等还会发生。** 本 change 只让这件事**可见可计数**，
   `SpinDetector` 与 `_signature` 一行未动。`test_guardrail_still_does_not_catch_this_pattern`
   把这个分界钉成了测试：同一批换参调用**信号命中、护栏判不出打转**。
   **收尾结论 MUST NOT 说成"打转问题解决了"。**
2. **规则对比表里的「2/3 命中」是离线复算出来的**，不是老 trace 真能报出来。分析脚本用
   完整 `args` 加一个显式宽度参数集重放才得出那个数；线上覆盖**自本 change 之后落的新
   trace 起生效**。刻意不给老 trace 加「按参数名硬编码回退推断」的分支——那等于把 design D2
   拒掉的域知识泄漏以"兼容"的名义请回来，且收益仅限那 6 个文件。
3. **「改写漂移」未覆盖**：同工具反复改写检索键、多步无进展（真实数据里 `search_knowledge`
   连查 6 次那条）规则 D 抓不到——检索键在变、身份不同。7 条数据里它只有 1 个正样本，硬做
   规则就是猜。`max_steps` 是它的兜底。已写成 `test_query_reformulation_not_covered`，
   让"已覆盖打转"这种误读没法成立。

### 再谈护栏的触发条件（别凭感觉提前做）

满足**两条**才立项改 `SpinDetector`：

1. 真实流量里 `repeated_tool_identity` 累计命中 **≥10 次**（够看清分布，不是个例）；
2. 人工复核这些命中，**误报率 < 20%**（即绝大多数确实是无进展的重复，而非正当枚举的新变体）。

届时还需先回答一个本 change 没解决的问题：**终止之后给用户说什么**——直接兜底回复会让
同事以为 bot 坏了，比多跑两步更糟。

### 不需要做的

**不重定 `evals/baseline.json`**：本 change 不改评分指标、不改运行时行为（预约域评测冻结）。
已确认 baseline 未被触碰。
