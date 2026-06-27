## Context

评估体系经改造 1–6 已具备离线能力：真跑 AgentLoop、参数/序列级工具指标、多采样置信区间、LLM-judge、CI 回归门禁。但 `agent-eval-fieldguide.md` §13 的「在线」闭环缺失——而且更底层的问题是：**生产入口 [api/chat_handler.py:53](../../../api/chat_handler.py) 的 `AgentLoop` 没注入 `tracer=`**，生产路径压根不产 trace。tracer / exporter 至今只在 `evals/`（`agent_capture.py`、`trace_collect.py`）和 `tests/` 里用。

既有可复用资产：
- `harness/observability/exporter.py`：`SpanExporter` Protocol（鸭子类型，`export(span)` 即可）、`InMemoryExporter`。
- `harness/observability/logging_exporter.py`：`LoggingSpanExporter` 已示范「span → 单行 JSON」（`to_dict()` + `ensure_ascii=False` + `default=str`），但走的是 logging、不落可检索文件。
- `harness/observability/span.py`：`Span.to_dict()` 已拍平为可序列化结构。
- `evals/trace_collect.py`：`collect_tool_calls(spans)` 从 span 还原有序工具序列（跨 span 按 `start` 排序、剔除 `delegate`）。
- `evals/agent_capture.py`：per-case `InMemoryExporter` 沙盒 + tracer 经 `build_delegate_tool(..., tracer=)` 透传子 Agent。
- `evals/run_evals.py:load_cases`：只校验 `expected_intent`，容忍额外字段（已读源码确认）。

约束：本项目自我定位学习/面试（`harness-refactor-plan.md:215` 明确防过度工程），两条铁律——**防过度工程**、**诚实标注**。

## Goals / Non-Goals

**Goals:**
- 让真实对话留下**可检索的持久化 trace**（落盘 JSONL），补上「产 trace」这一缺失环节。
- 提供**半自动 triage**：用已有客观信号挑出「疑似坏」trace，人工确认真值。
- 把人审通过的坏 case **回灌进 `evals/cases.jsonl`**（去重、溯源、提醒重定基线），跑通端到端闭环。
- 全部判定逻辑（trace 还原 / 甄别 / 去重）做成**纯函数 + 离线确定性单测**，无 key 可跑、可进闸门 2。

**Non-Goals:**
- 不搭真实流量采样基础设施（无真实用户）；「生产 trace」=开发/手动对话或回放输入，文档诚实标注。
- 不引入 OTel/外部 trace 后端依赖（默认路径仍零 OTel）。
- 不自动判定真值、不自动改 `cases.jsonl`/`baseline.json`——真值与基线变更都过人审。
- 不动既有 `bad_cases` DB 表（那是另一条运行时落库通路，本变更走文件 trace 通路）。
- 不扩用例集规模（那是改造 8）。

## Decisions

### D1 trace 来源：文件型 exporter 接进生产 AgentLoop
新建 `harness/observability/file_exporter.py::FileSpanExporter`，`export(span)` 把 `{"event":"span", **span.to_dict()}` 以单行 JSON 追加写目标文件。在 `chat_handler.py` 模块级构造 `Tracer(FileSpanExporter(...))` 注入主 `_agent_loop`，并经 `build_delegate_tool(..., tracer=)` 透传子 Agent（与 `agent_capture.py` 同款接法，才采得到领域工具）。
- **为何不复用 `LoggingSpanExporter`**：它走 logging，输出受 handler/格式器影响、不保证一个可逐行 `json.loads` 的稳定文件；triage 需要确定的可检索文件源。
- **替代方案**：复用既有 `bad_cases` DB 表落运行时坏 case。否决——那是 runtime 主动落「失败/纠正」的另一通路，与「采全量 trace 再事后甄别」口径不同；且 §13 原文就是「trace 采样」，文件 trace 更贴原意、也更易离线测。

### D2 采样：全量 + 错误优先，`sample_rate` 默认 1.0
默认落全部 trace。错误信号（`max_steps` 命中 / 工具异常 / 回复 `[ERROR]` / 兜底回复）**必留**，不受 `sample_rate` 影响；`sample_rate<1.0` 只对「非错误」trace 按比例采。学习项目流量极小，默认 1.0 最简；旋钮留着是为讲清「生产会按率采样、但错误不丢」这一判断力点。
- 采样决策放在**写盘前的一层薄封装**（按整条 trace 决定整体留/弃），而非 exporter 内逐 span 判（逐 span 判会切断同一 trace 的 span 树）。

### D3 健壮性：export 不得抛
`FileSpanExporter.export` 内 `try/except` 吞一切 IO 异常、失败仅 `logger.warning`，沿用 `exporter.py` 协议注释「同步、不得抛出以免影响主流程」与 `logging_exporter` 的 `default=str` 兜底。可观测不能拖垮主链路。

### D4 甄别：纯函数 triage，信号复用既有结构
`evals/triage.py` 提供 `triage_traces(traces) -> [candidate]`：输入「一次运行的 span 列表 / 一条 trace 记录」，输出候选（带命中的信号标签）。信号判定全靠 span 的 events/attributes 与回复文本，不触网、不调 LLM。复用 `collect_tool_calls` 还原工具序列、复用 `to_dict()` 的结构读字段。
- 工具异常信号：从 span 的 `observation` event / attributes 判（实现时对齐 tracer 实际写法）。

### D5 标注产物与 cases.jsonl 同构
从候选 trace 还原标注草稿：`input`（取自 root span attributes 或 trace 记录）+ 观测到的 `actual_tools`（`collect_tool_calls`）/ 槽位 / 回复，供人工填 `expected_*`。产物字段集 = `cases.jsonl` 现有口径（`input`/`expected_intent`/`expected_tools`/`expected_tool_args`/`expected_slots` + `source`）。人工编辑是闭环里**唯一**的真值来源（诚实原则）。

### D6 回灌去重 + 溯源
`append_cases(cases_path, new_cases) -> 报告`：纯函数读现有 `cases.jsonl`（跳过 `//` 注释与空行，与 `load_cases` 同口径），按 `input` 规范化（strip + 统一空白/大小写口径，对齐既有 metrics 的规范化思路）建集合，已存在则跳过并报告，新用例追加 `"source":"online"`，落在 `// --- online 回灌 ---` 分节下。`load_cases` 容忍额外字段，已读源码确认 `source` 安全。

### D7 回灌后不自动 re-baseline
回灌改变用例集 → 基线失真，但**自动重定基线会绕过改造 6 的人审闸门**。故 CLI 末尾只打印提醒「用例集已变更，需 `uv run python evals/run_evals.py --samples 3 --update-baseline`」，`baseline.json` 不被自动改。

### D8 存储与 gitignore
trace 落 `evals/traces/*.jsonl`，运行期产物，`.gitignore` 增 `evals/traces/`（与 `data/`、`logs/` 同类）。

### D9 测试：纯函数离线确定性
`FileSpanExporter`（写临时文件断言可逐行解析）、`triage_traces`、`append_cases` 全部离线可测，仿 `test_eval_gate.py` 的 `compare_to_baseline` 风格。生产接线（chat_handler）只做轻量「tracer 已注入且不改流式语义」的烟测，不强制端到端跑 LLM。

## Risks / Trade-offs

- [无真实流量，"在线"是模拟] → 文档（README + fieldguide §13）诚实标注边界；机制本身（产→采→标→回灌）真实可跑，面试讲清「真实生产会怎么接」即可。
- [生产接 tracer 增加每请求落盘开销] → 同步追加写、量小；`export` 吞异常不阻塞；`sample_rate` 旋钮可降量。
- [甄别只用客观信号，会漏「看起来正常其实答错」的坏 case] → 接受：triage 只负责把人工注意力引到高概率坏例，真值仍靠人审；漏检的可经后续手工补。诚实写进文档。
- [回灌污染用例集 / 重复] → `input` 规范化去重 + `source` 溯源 + 人审闸门；回灌后强制人工重定基线。
- [tracer 写盘文件无限增长] → 学习项目可接受；`evals/traces/` 已 gitignore，必要时手工清理（不在本变更范围内做轮转）。

## Migration Plan

1. 加 `FileSpanExporter` + 单测（不接生产，零影响）。
2. 接进 `chat_handler`（含子 Agent 透传 + 采样封装）；烟测流式语义不变。
3. 加 `evals/triage.py`（甄别 + 标注草稿 + 去重回灌）+ 纯函数单测。
4. `.gitignore`、`evals/README.md`、`docs/agent-eval-fieldguide.md` §13 文档同步。
5. 闸门 2：`uv run pytest`（含新单测）全绿；`run_evals.py --gate` 不回归。
- **回滚**：移除 chat_handler 的 tracer 注入即恢复原行为（exporter/triage 为独立新增文件，删之无副作用）。

## Open Questions

- 工具异常信号在 span 里的确切落点（event kind / attribute 名）需在实现时对齐 `tracer.py` / `agent_loop.py` 的实际写法——以代码为准，不预设。
- `input` 规范化的精确口径（是否折叠全角/标点）取既有 metrics 规范化函数为准，实现时复用而非另造。
