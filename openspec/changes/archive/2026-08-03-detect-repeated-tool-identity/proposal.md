## Why

`harness/guardrails/budget.py` 的 `_signature` 把参数计入签名（`(name, json.dumps(args, sort_keys=True))`），故参数一变签名就变、`SpinDetector` 的连击计数清零。**结果：同一工具被反复调用、每次参数不同的打转，护栏与可观测层双双看不见。**

在盘上 7 条真实 trace 上实测：**`连击=1` 出现在每一步、每一条 trace——现状规则抓到病态 0/3**。盲区是彻底的，不是边缘情况。

已被两次独立生产观测指向：

1. `feat/evals-dataset-scaleup` 分支复盘（commit `7d76c64`）：90 条负样本里同一工具连调 5-6 次，`repeat_limit=3` 未拦住，当时标为"另记"，随分支被放弃差点丢掉。
2. **真实飞书群聊（2026-08-03）**：模型追一个 requestId 时把 vlog 时间窗 6h→2d→7d 越拓越宽，连吃三次 60 秒超时、白等 3 分钟。护栏全程没拦；最后是靠 change `fix-trace-triage-blindspots` 新加的 `tool_timeout` 信号才在 triage 里捞出来的。

### 规则对比（已在真实数据上做完，不是推测）

7 条真实 trace，按参数序列语义人工标注 3 病态 / 3 正当 / 1 边界：

| 规则 | 抓到病态 | 误报正当 |
|---|---|---|
| 现状（连续整步签名全同 ×3） | **0/3** | 0 |
| B 同名连续 ×3（不看参数） | 3/3 | **3** ← 把正当枚举全打死 |
| B' 同名连续 ×4 | 2/3 | 2 |
| C 去掉宽度参数后连续 ×3 | 1/3 | 0 |
| **D 同 (工具, 身份参数) 出现 ≥3 步（不要求连续）** | **2/3** | **0** |

**关键发现：最直觉的修法 C 只有 1/3。** 因为真实 step **一步里常有多个工具调用**（如那条坏 trace 的 step2 同时查了 prod/30m 与 uat/2d），"连续整步签名相同"这个形状一遇多调用就散。所以问题**不在签名怎么算，在判据形状本身错了**——这也是为什么本 change 不是"把参数从签名里剔掉"这么一行的事。

规则 D 正确放过的三种正当模式：**逐租户枚举**（term/window 固定、env 走 prod→uat→stg→dev）、**换检索策略后收窄**（logsql→term）、**多意图并行检索**。这正是它相对 B/B' 的全部价值。

## What Changes

**1. `Tool` 新增「宽度类参数」声明**

宽度类参数 = 只影响检索范围、不改变"在找什么"的旋钮（`window` / `limit` / `top_k`）。域知识声明在 `Tool` 上、机制保持域无关——判据与 `Tool.timeout` 同源（见 roadmap 第 1 期「超时值声明在 `Tool` 上而非运行时全局常量」，理由完全一致：全局常量对不同工具必然误伤）。

**2. 记录时提取「身份参数」**

`detect_bad_signals` 是纯函数、只看 span、**拿不到 `ToolRegistry`**，故它无从知道哪些参数属宽度类。解法沿用 change `fix-trace-triage-blindspots` 的 `error_kind` 那套：由**持有 registry 的 `AgentLoop`** 在记录 `tool_call` 时把身份参数子集一并写进 event payload，判定侧保持纯净。

MUST NOT 让 `trace_signals` 硬编码参数名白名单——那是把域内容泄漏进 `harness/`，与记忆层那三处已知泄漏同类，不能再添一处。

**3. `trace_signals` 新增 `repeated_tool_identity` 信号**：按规则 D 判定。它自动进入既有的「错误优先留存」（`is_bad_trace`）与 triage 候选/信号计数摘要，无需改那些机制。

**4. 域侧声明**：`vlog_query` 声明 `window`/`limit`；`search_knowledge` 声明 `top_k`。

## Capabilities

### New Capabilities
<!-- 无新增能力：三处都是既有 tool-layer / observability / bad-case-feedback 能力的增补 -->

### Modified Capabilities

- `tool-layer`: `Tool` 声明面新增「宽度类参数」，用于把「哪些参数不构成调用身份」这一**域知识**留在工具定义处，而非泄漏进域无关运行时。
- `observability`: `tool_call` 事件 MUST 携带据上述声明算出的身份参数；失控信号集新增 `repeated_tool_identity`（规则 D），并明确它 MUST NOT 依赖硬编码参数名。
- `bad-case-feedback`: triage 甄别的可用信号集随之扩大（同工具换参重复进候选）。

## Impact

**代码**

- `harness/tools/base.py`：`Tool` 新增宽度类参数字段（缺省空 → 行为与声明前一致）。
- `harness/runtime/agent_loop.py`：记录 `tool_call` 时按 registry 里的声明算出身份参数并传给 tracer。
- `harness/observability/tracer.py`：`add_tool_call` 接受并记录身份参数。
- `harness/observability/trace_signals.py`：新增 `repeated_tool_identity` 判定。
- `domains/oncall/tools/vlog.py`、`domains/appointment/tools/`（`search_knowledge`）：声明各自的宽度类参数。

**不改（明确非目标，勿含糊成"都覆盖了"）**

- **不改 `SpinDetector`、不改 `_signature`、不提前终止循环。** 人审拍定：终止循环是生产行为变更，而预约域评测网是知情放弃的弱网（41 条、只存点估计无 CI），误杀风险没有网兜。**先让机制看得见，再谈拦**——与 change `fix-trace-triage-blindspots` 同一套路。攒够数据（这类模式多久出现一次、多少是正当枚举）再单独立项谈护栏。
- **不覆盖「改写漂移」**：同工具反复改写检索键、多步无进展（真实数据里 `search_knowledge` 连查 6 次那条）规则 D 抓不到——检索键本身在变、身份不同。那是另一个问题，`max_steps` 是它的兜底；7 条数据里它只有 1 个正样本，规则可靠性远不如 D，硬做会是猜。
- 不动 `services/`、不改工具行为、不改评分指标、不重定 `evals/baseline.json`（预约域评测冻结）。

**验证**

- `uv run pytest` 全绿。
- MUST 有回归测试复现那 7 条真实 trace 的形状，断言规则 D 的「2/3 命中、0 误报」特性；**尤其要有一条钉住「逐租户枚举 MUST NOT 命中」**——那是本规则相对 B/B' 的全部价值所在。
- ⚠ 测试用 span MUST 是**合成的**（真实 requestId 与同事原话须换掉）：trace 目录 gitignore，但测试进版本库——与「回灌 `cases.jsonl` 不得带 `user_id`」同一个道理。
- 诚实边界须写进 tasks 收尾：**已落盘的老 trace 无法命中此信号**（老 payload 没有身份参数字段）；那「2/3 命中」是离线用完整 args 复算出来的，不是老 trace 真能报出来。覆盖自本 change 之后的新 trace 起生效。
