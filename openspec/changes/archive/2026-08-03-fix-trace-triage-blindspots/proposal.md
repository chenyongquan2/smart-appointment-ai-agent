## Why

值守 bot 已接入飞书群、真实流量在落（盘上 6 个 trace 文件 / 29 次 `agent_loop.run`，DB 11 个 session / 48 轮，最新到 2026-08-03）。但 `evals/triage.py scan` 对这批真实 trace 得 **0 个疑似坏候选**——而真实群聊里明确发生过一次坏 case：模型追 traceId 时把窗口 6h→2d→7d 越拓越宽，**连吃三次 60 秒超时、白等 3 分钟**（见 commit `b5b5011`）。

已实证复现，两条独立漏因：

```
TOOL_FAILURE_PREFIX = '工具执行失败'
A  loop 级工具超时（agent_loop.py:322）      -> [] ← 漏
B  service 级超时结构化返回（vlog.py:474）   -> [] ← 漏
C  普通工具异常（agent_loop.py:324）         -> ['tool_failure']
真实群聊那次（三连超时后仍给出回复）        -> [] ← 漏
```

1. `agent_loop.py:322` 返回「工具执行**超时**（…）」，而 `trace_signals.py:26` 的 `TOOL_FAILURE_PREFIX` 是「工具执行**失败**」，`startswith` 不匹配。**根因是同一句文案在两个模块各写了一份**：超时支当初是刻意从通用 `Exception` 支拆出来的（为给模型一句更明确的说明），拆的时候把信号一起拆断了，而没有任何机制会提醒。
2. service 级超时是**结构化成功返回**（`services/vlog.py:474` 的 `error_kind="timeout"`），从 loop 看根本不是异常，`_dispatch` 无从判定。

连带后果：`SamplingSpanExporter` 的「命中失控信号必留」靠 `is_bad_trace` 判定，故**超时类 trace 不在必留范围内**。当前 `EVAL_TRACE_SAMPLE_RATE=1.0` 全量留，没丢东西；一旦有人为省盘调低采样率，丢掉的恰好是最该留的那批。

这是同一个模式的第三次出现：**沉默不是中立**。前两次在工具层（超时不给建议 = 默许模型继续加宽窗），这次在可观测层（信号不报 = 默许「一切正常」）。

**为什么是现在**：[docs/oncall-bot-roadmap.md](../../../docs/oncall-bot-roadmap.md) 文末「处理顺序」第 2 步是「真实 trace 跑 triage（零标注）」，而这批 trace 正是第 4 期数据集的原料。不修就是每多跑一天，多攒一天「最常见的真实故障不可见」的 trace。

顺带两个同层缺口，一并做（同一个改动面，分开做要动三次同样的文件）：`Span.to_dict()` 只存 `latency` 不存墙钟时刻，triage 只能拿文件行序当 synthetic start，没法按日期切窗、没法把 trace 与飞书某条消息对时间；trace 里 **distinct user_id = 0**——第 1 期特意把发送者 open_id 当 `user_id` 传进去避免 34 人混成一个 `default_user`，但它只进了 DB、没进 trace。

## What Changes

**1. 超时纳入失控信号（本 change 的主体）**

- 新增信号标签 `tool_timeout`，**与 `tool_failure` 分开**而不并入：两者的补救动作不同（超时 → 收窄查询；失败 → 参数错/服务报错），合并会让 triage 的候选失去可操作性。
- **loop 级路径**：把「工具执行失败」/「工具执行超时」两句文案收敛为**单一真相源**，由 `harness/observability/` 导出常量、`agent_loop._dispatch` 引用。根因是文案被复制了两份，只改匹配串等于把同一个坑留给下一个人。
- **service 级路径**：`Tracer.add_observation` 在 `str()` 化之前，把结果对象里的 `error_kind` **结构化提取**进 event payload；`detect_bad_signals` 读 `payload["error_kind"]` 判定。刻意不做「在字符串里 substring 匹配 `error_kind`」——那违反项目黄金准则「结构化输出 > 字符串解析」，且 `str(dict)` 的格式不是契约。
- 修正 `trace_signals.py` docstring 里两处**现在已不成立的表述**：它自称「严格对齐 `AgentLoop` 的真实落点」（实际只对齐了两个落点里的一个）；`observability` spec 的信号枚举里写着「回复带 `[ERROR]`」，而该前缀是遗留 `agents/` 路径的产物、当前生产的 harness 路径只产 `[REPLY]`（`trace_signals.py:13` 自己已注明，spec 没跟上）。

**2. Span 增加墙钟时间戳**

- `Span` 新增 `started_at`（墙钟，UTC ISO8601），进 `to_dict()`；`start`/`end` 保持单调 clock 语义不变（算 latency 用），**两者不混用**。
- 墙钟来源**同样可注入**（`Tracer(wall_clock=...)`，缺省 `datetime.now(UTC)`），沿用既有 `clock` / `id_factory` 的可注入纪律，确定性单测不被破坏。
- `triage.load_trace_spans` 优先用 `started_at` 排序/切窗，**缺失时回退文件行序**——盘上已有 6 个不带该字段的真实 oncall trace 文件，MUST NOT 让它们失效。
- triage 新增按时间窗过滤（如 `--since`），使「这周新增了哪些坏 case」可问。

**3. Span 携带 user_id**

- `AgentLoop.run()` 新增可选参数 `user_id`（缺省 `None`，行为向后兼容），写进 root span 的 attributes；`api/chat_handler.py` 在既有 `loop.run(...)` 调用点传入已有的 `user_id`。
- ⚠ **为何必须是 per-call 参数而非构造参数**：`AgentLoop` 是跨请求共享的模块级单例，构造期持有 user_id 会在并发会话间串号。这与 `on_outcome` 参数的既有理由完全一致（见 `agent_loop.py:146-149` 的 docstring），照同一个判据办。
- **隐私边界**：`user_id` 是飞书 open_id（应用内作用域的不透明标识，非姓名/邮箱），DB 里已以原样存在，故 trace 也存原样——脱敏会切断 trace↔DB 的关联，而关联正是它的用途。三条硬约束：trace 文件保持在 `.gitignore` 内、不出宿主机；**回灌 `cases.jsonl` MUST NOT 带 user_id**（`triage.CANONICAL_KEYS` 白名单当前已不含它，属「碰巧安全」，本 change 补一条回归测试把它钉死，因为 `cases.jsonl` 是**进版本库**的）。

## Capabilities

### New Capabilities
<!-- 无新增能力：三项都是既有 observability / bad-case-feedback 能力的口径修正与增补 -->

### Modified Capabilities

- `observability`: 失控信号口径新增「工具超时」两条路径（loop 级 + service 级 `error_kind`），并修正枚举里「回复带 `[ERROR]`」这条已不成立的表述；Span 模型新增墙钟时间戳（与既有单调 clock 并存、语义不混）；span attributes 新增 `user_id`（含隐私边界要求）。
- `bad-case-feedback`: 从持久化 trace 甄别坏 case 的候选口径随信号扩大（超时类 trace 进候选）；`load_trace_spans` MUST 兼容不带墙钟字段的历史 trace 文件；新增按时间窗筛选候选；回灌 `cases.jsonl` MUST NOT 携带 `user_id`。

## Impact

**代码**

- `harness/observability/trace_signals.py`：新增 `tool_timeout` 信号与超时判定；文案常量单一真相源；修正 docstring。
- `harness/observability/span.py`：新增 `started_at` 字段并进 `to_dict()`。
- `harness/observability/tracer.py`：新增可注入 `wall_clock`；`add_observation` 结构化提取 `error_kind`。
- `harness/runtime/agent_loop.py`：`_dispatch` 的两句文案改引用常量；`run()` 新增可选 `user_id` 并写入 root span attributes。
- `evals/triage.py`：`load_trace_spans` 用 `started_at`（缺失回退行序）；`scan` 新增时间窗筛选。
- `api/chat_handler.py`：`loop.run(...)` 传入既有 `user_id`（一行）。

**不改**

- `services/`（包括 `vlog.py` 的返回契约）、`AgentLoop` 的控制流与工具行为、`SamplingSpanExporter` 的采样机制本身（它自动受益于信号口径变宽）。
- 不扩预约域评测、不重定 `evals/baseline.json`——见「预约域评测冻结」。本 change 不改任何评分指标，不触发基线变更。

**⚠ 诚实标注的一处越界**：立项时说的边界是「只动可观测层」，但第 3 项要给 `AgentLoop.run()` 加一个可选参数（`harness/runtime/`）。它只喂 span attributes、不参与任何决策、缺省 `None` 时行为完全不变，故判为可接受；但它确实动了运行时的签名，写在这里供人审时否决。

**验证**

- `uv run pytest` 全绿。
- MUST 有一条回归测试直接钉住「真实群聊那次三连超时」这个形状：构造 loop 级超时串 + service 级 `error_kind=timeout` 的 span，断言 `detect_bad_signals` 不再返回空。
- MUST 有一条测试证明盘上**不带 `started_at` 的历史 trace 文件仍能被 triage 加载**。
- MUST 有一条测试证明回灌后的 `cases.jsonl` 不含 `user_id`。
