## Context

值守 bot 已在飞书群产生真实流量，但 triage 对这批 trace 报「0 个疑似坏候选」，而真实群聊里确实发生过连吃三次 60 秒超时的坏 case。三处缺口都在可观测层，且都属于「机制在，但口径没对齐真实落点」。

实施前已核实的现状（这些事实直接决定了下面的取舍，不是推测）：

| 事实 | 出处 | 对设计的约束 |
|---|---|---|
| `add_observation` 拿到的是**未 str() 化的原始返回值**（`str()` 只发生在下一行包 `ToolMessage` 时） | `agent_loop.py:245-251` | 结构化提取 `error_kind` 可行，无需改工具契约 |
| `vlog` 工具 handler 返回 `dict`，失败时 dict 里带 `error_kind` | `domains/oncall/tools/vlog.py:18,48` + `services/vlog.py:128,474,530` | 提取目标就是这个键 |
| **`repo` 服务用的是 `status` 字段，且 `need_clone`/`branch_not_found` 等被显式定义为「正常引导状态、不是异常」** | `services/repo.py:68,76,90` + `domains/oncall/tools/code.py:71-72` | ⚠ **绝不能泛化判定「任何错误类字段」**，否则引导状态会变成误报候选 |
| `harness/runtime/__init__.py` **导入 `AgentLoop`**；`AgentLoop` 又导入 `observability.tracer` | 两个文件首部 | 文案常量放 `harness/runtime/` 下会造成 import 期成环 |
| `harness/__init__.py` 只有 docstring、零 import | 该文件 | `harness/` 顶层新模块是安全落点 |
| `otel_exporter` 读 `s.attributes`、**不读 `to_dict()`**；`logging_exporter` 展开 `to_dict()` | 两个 exporter | 给 `to_dict()` 加字段不会打坏 OTel 路径 |
| `evals/traces/` 已在 `.gitignore` | `.gitignore:42` | user_id 落盘不进版本库这一前提成立 |
| 盘上已有 6 个**不带**墙钟字段的真实 trace 文件 | `evals/traces/` | 新字段必须向后兼容，不得让它们失效 |

## Goals / Non-Goals

**Goals:**

- 工具超时（loop 级中断 + service 级结构化）成为可被 triage 与采样留存识别的失控信号。
- 消除「同一句文案在两处各写一份」这个**根因**，使文案再改也不会静默断开信号。
- span 带绝对时间与提交者标识，使「本周新增哪些坏 case」「这条是谁的对话」可回答。
- 保持既有 6 个真实 trace 文件可用。

**Non-Goals:**

- 不统一 `services/` 各自的错误约定（`vlog` 用 `error_kind`、`repo` 用 `status`+`error`）。那是 services 层改动，且 `repo` 的引导状态设计本身是对的，不该为可观测层的便利去改它。见「Open Questions」。
- 不改 `AgentLoop` 控制流、不改工具行为、不改 `vlog` 返回契约。
- 不动采样机制本身（它靠 `is_bad_trace`，信号口径变宽后自动受益）。
- 不改任何评分指标、不重定 `evals/baseline.json`（预约域评测冻结）。
- 不把墙钟时刻接进 OTel span（OTel 有自己的 start_time，另一码事）。

## Decisions

### D1：文案单一真相源放在 `harness/tool_outcome.py`，且导出**格式化函数**而非仅前缀

新增 `harness/tool_outcome.py`（顶层小模块）导出 `TOOL_FAILURE_PREFIX` / `TOOL_TIMEOUT_PREFIX` 与两个格式化函数 `tool_failure_message(name, exc)` / `tool_timeout_message(name, timeout)`。`agent_loop._dispatch` 改为调这两个函数，`trace_signals` 匹配这两个前缀。

**为何不放 `trace_signals.py` 里让 runtime 去 import**：那等于让可观测层拥有运行时**喂给模型看的文案**。方向上不成环、能跑，但职责错位——下一个人改文案时不会想到去 observability 找。

**为何不放 `harness/runtime/` 下让 observability 去 import**：**实测会成环**。`harness/runtime/__init__.py` 导入 `AgentLoop` → `AgentLoop` 导入 `harness.observability.tracer` → 若 `trace_signals` 反向导入 `harness.runtime.*`，import 期即循环。且会让轻量的 exporter 拖进整个 langchain 依赖树。

**为何导出函数而不只是前缀常量**：只共享前缀的话，`agent_loop` 仍持有 `f"{PREFIX}（{name}）：…"` 的拼装，下一个人改动括号或分隔符照样能悄悄破坏 `startswith`。把整句的生成权交给单一模块，runtime 就没有可漂移的余地——这才是对根因下药，而不是把匹配串改对了完事。

### D2：service 级超时靠**结构化字段**判定，且只认 `error_kind` 这一个键

`Tracer.add_observation` 在 `str()` 化之前做一次窄提取：结果是 Mapping 则取 `result.get("error_kind")`，否则 `getattr(result, "error_kind", None)`；仅当取到**非空字符串**时写入 event payload 的 `error_kind` 键。`detect_bad_signals` 读该键判定：`"timeout"` → `tool_timeout`；其它非空值（`connect_failed` / `http_error` / `other`）→ `tool_failure`。

**为何不在字符串里 substring 匹配**：违反项目黄金准则「结构化输出 > 字符串解析」，且 `str(dict)` 的排版（引号、空格、键序）不是任何契约，Python 版本或返回类型一变就断。

**⚠ 为何只认 `error_kind`、不泛化成「任何错误类字段」**：`services/repo.py` 的 `status` 里 `need_clone` / `branch_not_found` / `bad_env` / `need_git_url` 被**显式定义为正常引导状态**（`GUIDE_STATUS`，且 `ok` 属性就是 `status in GUIDE_STATUS`）。泛化判定会把「仓库还没备好，请运维 clone」这种正常引导变成疑似坏候选——triage 的价值全在信噪比，误报比漏报更能毁掉它。`error_kind` 之所以安全，是因为它在 `services/vlog.py` 里**只在超时与异常分类两条真失败路径上被赋值**。

**顺带修掉的一类漏报**：`connect_failed` / `http_error` / `other` 今天同样完全不可见（不只超时）。它们与超时走同一段代码，一并覆盖不构成额外风险；不覆盖反而是明知有漏还留着。

**为何只提一个键、不把整个结果对象塞进 payload**：`vlog` 的结果里含真实生产日志正文，体积大且含业务内容；payload 只该留判定所需的最小结构。

### D3：`tool_timeout` 与 `tool_failure` 分开成两个标签

超时的补救是**收窄查询**，普通失败通常是参数错或下游报错——补救动作不同，合并会让候选清单失去可操作性。这与工具层「超时一律给可操作建议」的口径一致：分类本身就是信息。

### D4：墙钟用 ISO8601 UTC 字符串存 `Span.started_at`，clock 与 wall_clock 并存不混用

- `Span` 新增 `started_at: Optional[str]`，进 `to_dict()`；既有 `start`/`end` 保持 `perf_counter` 单调语义（算 latency，不受系统时间回拨影响）。**两套时间各司其职，绝不互相替代。**
- `Tracer` 新增可注入 `wall_clock: Callable[[], datetime]`，缺省 `lambda: datetime.now(timezone.utc)`；`start_span` 里格式化成 ISO 串。沿用既有 `clock` / `id_factory` 的可注入纪律，确定性单测不受真实时间影响。
- **为何存字符串而非 epoch float**：JSONL 要人能直接看、能 `grep`；且固定为「UTC + 同一格式」时字典序即时间序，triage 排序与 `--since` 比较都不必先解析。代价是比 float 略占空间，可接受。
- **为何是新字段而不是把 `start` 改成墙钟**：latency 必须由单调时钟算，改了会在系统时间回拨时得出负耗时。

### D5：`user_id` 走 `run()` 的**每次调用参数**，存原样 open_id

- `AgentLoop.run(..., user_id=None)`，写进 root span attributes；`api/chat_handler.py` 在已有调用点传入现成的 `user_id`（该函数签名里已有，见 `chat_handler.py:140`）。
- **为何不是构造参数**：`AgentLoop` 是跨请求共享的模块级单例，构造期持有会在并发会话间串号。这与 `on_outcome` 的既有理由完全同源（`agent_loop.py:146-149` 已把这条判据写下来了），照同一个判据办，不另立一套。
- **为何存原样、不脱敏**：open_id 是应用内作用域的不透明标识（非姓名/邮箱），DB 里已以原样存在；哈希会切断 trace↔DB 的关联，而关联正是它的用途。边界靠**位置**而非**变形**来守：`evals/traces/` 已 gitignore；`cases.jsonl` 进版本库，故回灌白名单 `triage.CANONICAL_KEYS` 不含 `user_id`——今天是「碰巧安全」，本 change 补测试把它钉死。

### D6：triage 优先 `started_at`，缺失回退行序；时间窗筛选**纳入并报数**，绝不静默丢弃

`load_trace_spans` 保持现有「行序当 synthetic start」的机制（`to_dict` 不存 start/end，这是既有事实），额外读入 `started_at`。`--since` 筛选时，无该字段的历史记录**一律纳入**并在输出里报告其条数。

**为何纳入而非排除**：那 6 个文件是**真实 oncall 流量**，是目前唯一的真实原料。排除等于为了口径整齐丢掉真数据；而静默排除更糟——它会让「0 个候选」这个结论第二次骗人。

### D7：历史 trace 的可恢复程度——诚实标注

修完之后，对**已落盘的 6 个文件**：

- **loop 级超时可被识别**：`_dispatch` 的超时说明字符串本来就存在 observation 的 `result` 里，前缀匹配对老文件同样生效。真实群聊那次三连超时属于此类（`Tool.timeout` 60s 掐断），**故它应当在修完后浮现出来**——这是一次能在真实数据上验证的端到端检查，写进 tasks。
- **service 级结构化超时对老文件仍不可见**：老 payload 里没有 `error_kind` 键，只有 `str(dict)`。**刻意不为此加「老文件走 substring 回退」的兼容分支**——那等于把刚拒掉的字符串解析请回来，且收益仅限于这 6 个文件。如实标注：该路径的覆盖自本 change 之后的新 trace 起生效。

## Risks / Trade-offs

- **[误报把 triage 淹掉]** → 只认 `error_kind` 一个键、且已核实它只在真失败路径赋值；`repo` 的引导状态明确排除。修完后先在真实的 6 个文件上跑一遍看候选数量与内容是否合理，再谈继续攒量。
- **[`add_observation` 里做类型探测引入异常]** → 提取逻辑必须自身不抛（Mapping/getattr 都可能遇到怪对象）；可观测是附属能力，沿用 `end_span` 吞异常的既有取舍，失败就当没提取到。
- **[`to_dict()` 多一个键打坏下游]** → 已核实 `otel_exporter` 走 `s.attributes` 不走 `to_dict`；`logging_exporter` 展开 `to_dict` 只多一个日志字段。`triage.load_trace_spans` 用 `.get()` 读，老文件缺键不报错。
- **[open_id 进落盘文件的隐私面]** → 位置守边界（trace 目录 gitignore、回灌白名单排除并加测试）。剩余暴露面与 DB 已有的一致，不新增外流通道。
- **[给 `run()` 加参数越出「只动可观测层」]** → 已在 proposal 里显式标注供人审否决。它只喂 span attributes、不参与决策、缺省时行为不变。
- **[老 trace 的 service 级超时仍漏]** → 接受并如实记录（D7）。不为 6 个文件引入字符串解析回退。

## Open Questions

1. **两个 oncall service 的错误约定不一致**（`vlog` 用 `error_kind`，`repo` 用 `status` + `error`）。本 change 刻意不统一——`repo` 的引导状态设计是对的，且改 services 越界。但这意味着**将来新加的 service 若发明第三种约定，信号又会漏**。是否要在 `openspec/project.md` 里立一条「工具失败一律用 `error_kind` 表达」的约定？倾向于要，但作为独立的小 change 做。
2. **`--since` 的时区**：`started_at` 统一 UTC，但人在飞书上看到的是本地时间。CLI 是否接受本地时间输入并转换？倾向于只收 UTC/带偏移的 ISO 串、不猜时区（参考系统栽过告警时区的坑）。
3. 本 change 是否顺带给 `evals/triage.py scan` 的输出加上「按信号分类的计数摘要」？目前它只打候选总数，攒量之后会需要「这周超时 12 次、打转 3 次」这种视图。倾向于加，成本很低。
