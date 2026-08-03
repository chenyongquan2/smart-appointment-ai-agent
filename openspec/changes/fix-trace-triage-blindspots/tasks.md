## 1. 文案单一真相源（先做——后面两处都依赖它）

- [x] 1.1 新增 `harness/tool_outcome.py`：导出 `TOOL_FAILURE_PREFIX` / `TOOL_TIMEOUT_PREFIX` 与格式化函数 `tool_failure_message(name, exc)` / `tool_timeout_message(name, timeout)`（design D1）。模块 MUST 零重依赖（不 import langchain / observability / runtime），否则会把成环风险搬回来。
- [x] 1.2 `harness/runtime/agent_loop.py` 的 `_dispatch` 改调这两个函数，删掉两处字面量拼装（`agent_loop.py:322` 与 `:324`）。**行为必须逐字不变**——文案改了会影响模型下一轮的判断，本 change 不做这种改动。
- [x] 1.3 `harness/observability/trace_signals.py` 改为从 `harness/tool_outcome.py` 导入前缀，删掉自己那份 `TOOL_FAILURE_PREFIX` 字面量（保留 `__all__` 里的再导出以免打断既有 import 方）。
- [x] 1.4 加测试：断言 `agent_loop` 产出的超时/失败文案与 `trace_signals` 匹配的前缀同源——即改动格式化函数后两侧一致。这条是**防再次漂移的机制**，不是可选项。

## 2. 超时纳入失控信号

- [x] 2.1 `trace_signals.detect_bad_signals` 新增 `tool_timeout` 标签，识别 loop 级超时（按 `TOOL_TIMEOUT_PREFIX` 匹配 observation 的 `result`）。与 `tool_failure` **分开**、不合并（design D3）。
- [x] 2.2 `Tracer.add_observation` 在 `str()` 化之前窄提取 `error_kind`：Mapping 取 `.get`、否则 `getattr`，仅当非空 `str` 时写入 payload 的 `error_kind` 键。提取逻辑**自身不得抛**（遇怪对象当没提取到）。**只提这一个键**，绝不把整个结果对象塞进 payload（design D2）。
- [x] 2.3 `detect_bad_signals` 读 `payload["error_kind"]`：`"timeout"` → `tool_timeout`；其它非空值（`connect_failed` / `http_error` / `other`）→ `tool_failure`。
- [x] 2.4 ⚠ 加测试钉住**不得泛化**：构造 `services/repo.py` 那种带 `status="need_clone"` 的正常引导返回，断言**不产生任何信号**。`GUIDE_STATUS` 是显式的正常状态，误报会毁掉 triage 的信噪比（design D2）。
- [x] 2.5 ★ 加回归测试钉住**真实群聊那次三连超时**的形状：同一工具连续三次 loop 级超时、最终仍产出终态回复 → 断言信号清单非空。这是本 change 存在的理由，测试名里写明它对应的真实事件。
- [x] 2.6 加测试：service 级 `error_kind="timeout"`（loop 层面无任何异常）→ 命中 `tool_timeout`。
- [x] 2.7 加测试：`sample_rate < 1.0` 且仅命中超时信号 → trace 仍被 `SamplingSpanExporter` 保留（验证 `is_bad_trace` 口径同步生效）。
- [x] 2.8 修正 `trace_signals.py` 的 docstring：它自称「严格对齐 `AgentLoop` 的真实落点」而实际只对齐了两个落点里的一个；同时把 `[ERROR]` 那段注释更新为「已在 spec 层一并修正」。

## 3. Span 墙钟时间戳

- [x] 3.1 `harness/observability/span.py`：新增 `started_at: Optional[str] = None`（ISO8601 UTC），加进 `to_dict()`。`start`/`end` 的单调 clock 语义**保持不变**，docstring 里写明两套时间各司其职、不得互相替代（design D4）。
- [x] 3.2 `harness/observability/tracer.py`：新增可注入 `wall_clock: Callable[[], datetime]`（缺省 `datetime.now(timezone.utc)`），`start_span` 里格式化成 ISO 串填入 `started_at`。
- [x] 3.3 加测试：注入固定墙钟 → 落盘 span 的 `started_at` 为该固定值（确定性可断言）；同时断言 latency 仍由注入的单调 clock 算出、两者互不影响。
- [x] 3.4 核对 `NoopTracer` 仍正常（它复用父类 `start_span`）：加一条断言它不因新字段而报错、也不产生导出。

## 4. Span 携带 user_id

- [x] 4.1 `AgentLoop.run()` 新增可选参数 `user_id`（缺省 `None`），写进 root span attributes。docstring 里写明**为何必须是 per-call 参数而非构造参数**（单例串号），并指向 `on_outcome` 的同源理由（design D5）。
- [x] 4.2 `api/chat_handler.py` 在既有 `loop.run(...)` 调用点（`chat_handler.py:201`）传入现成的 `user_id`。
- [x] 4.3 加测试：同一会话内两个不同提交者各跑一次 → 两次 root span 各带对应 `user_id`；不传时 span 不含该属性且行为与接入前一致。
- [x] 4.4 ★ 加测试钉住隐私边界：从一条 root span 带 `user_id` 的候选回灌，断言追加进 `cases.jsonl` 的用例**不含 `user_id`**。`triage.CANONICAL_KEYS` 今天碰巧安全，这条测试把它变成契约（`cases.jsonl` 进版本库、trace 目录不进）。

## 5. triage 侧接入

- [x] 5.1 `evals/triage.py` 的 `load_trace_spans` 读入 `started_at`（`.get()` 读，缺键不报错），保留既有「行序当 synthetic start」机制不变。
- [x] 5.2 `scan` 新增时间窗筛选（如 `--since`，只收 UTC 或带偏移的 ISO 串、**不猜时区**）。无 `started_at` 的历史记录**一律纳入**，并在输出里明确报告其条数——绝不静默丢弃（design D6）。
- [x] 5.3 加测试：同时含带/不带 `started_at` 的 trace 目录施加 `--since` → 不带该字段的被纳入且计数被报告出来。
- [x] 5.4 加测试：对不含 `started_at` 的既有格式 trace 文件跑甄别 → 正常解析，结果与引入新字段前一致（保证盘上 6 个真实文件不失效）。
- [x] 5.5 `scan` 输出加按信号分类的计数摘要（「超时 N 次 / 打转 M 次」）。design Open Question 3 倾向于加、成本很低；若人审认为越界则跳过本条并在 tasks 里划掉。

## 6. 验证

- [x] 6.1 `uv run pytest` 全绿——成功静默、只报错。
- [x] 6.2 ★ **在真实数据上验证**：对盘上已有的 6 个 trace 文件重跑 `uv run python -m evals.triage scan`。预期真实群聊那次三连超时（loop 级，前缀匹配对老文件同样生效）**浮现为候选**。如果仍是 0，说明修复没打到真实落点，MUST 回到 2.1 复查而不是改测试。
- [x] 6.3 人工核对 6.2 出来的候选内容与数量是否合理（信噪比体检）：引导状态类返回 MUST NOT 出现在候选里。
- [x] 6.4 如实记录 D7 的诚实边界：老文件的 **service 级**结构化超时仍不可见（老 payload 无 `error_kind` 键），该路径覆盖自本 change 之后的新 trace 起生效。写进本文件末节，不含糊过去。
- [x] 6.5 更新 `docs/oncall-bot-roadmap.md` 文末「处理顺序」表：第 2 步的前置已解除，可以开始攒量跑 triage。
- [x] 6.6 归档前确认**不需要**重定 `evals/baseline.json`——本 change 不改任何评分指标（预约域评测冻结，见 roadmap 开头）。

---

## 收尾结论（2026-08-03）

### 真实数据验证：0 → 3 个候选，全是真的

对盘上已有的 6 个 trace 文件（29 次 `agent_loop.run`）重跑 `uv run python -m evals.triage scan`：

```
修前：扫描 6 个 trace 文件，得 0 个疑似坏候选
修后：信号分布：tool_timeout 3 次
      扫描 6 个 trace 文件，得 3 个疑似坏候选
```

三条候选逐一核对，**全部是真实群聊 2026-08-03 那次坏 case**，零误报：

| 候选 | 观测到的工具 | input 前段 |
|---|---|---|
| 1 | `vlog_query`×2 + `load_reference`×2 | 「范围扩大为最近7天，prd环境的…」← 就是拓宽窗口那一轮 |
| 2 | `load_reference` + `vlog_query`×4 + `load_reference` | 「是ocs4的」 |
| 3 | `vlog_query`×4 | 「看一下这个requestId:36a29ab7c…」← 追 traceId 连打四次 |

**信噪比体检通过**：29 次运行里标出 3 条；`locate_service_code` 那类返回引导状态
（`need_clone` 等）的运行**没有**混进候选，说明「不泛化判定任何错误类字段」这条守住了。

`--since` 两条路径也在真实目录上验过：30 条无墙钟时间戳的历史 trace 被**明确报数**
（「已全部纳入」）而非静默丢弃；裸时间串 `2026-08-01T00:00:00` 被直接拒并给出改法。

测试：**608 passed / 1 skipped**（修前 578，新增 30 条）。

### ⚠ 诚实边界（勿在别处含糊掉）

1. **老文件的 service 级结构化超时仍不可见。** 已落盘 trace 的 observation payload 里
   没有 `error_kind` 键（只有 `str(dict)`），故 D2 那条路径对它们不生效。**刻意不加
   「老文件走 substring 回退」的兼容分支**——那等于把刚拒掉的字符串解析请回来，且收益
   仅限这 6 个文件。该路径的覆盖**自本 change 之后的新 trace 起生效**。
   上面能捞出 3 条，靠的是 loop 级前缀匹配（那句话本来就存在于老 payload 的 `result` 里）。
2. **候选 ≠ 坏 case 定论。** triage 只产候选与草稿，真值仍待人审填 `expected_*`。
   这三条尚**未**回灌 `cases.jsonl`——回灌是第 4 期下半的事，且要人工标注。
3. **不需要重定 `evals/baseline.json`**：本 change 不改任何评分指标、不动数据集
   （预约域评测冻结）。已确认 `baseline.json` 未被触碰。
4. **`--since` 只按 UTC/带偏移的 ISO 串工作**，不猜本机时区（design Open Question 2 的定案）。
   人在飞书上看到的是本地时间，跨时区查时需自己换算——这是刻意的，猜错会安静地把窗口挪几小时。

### design Open Question 的处置

- **Q1（工具失败一律用 `error_kind` 的约定）**：**未做**，留待独立小 change。现状是
  `vlog` 用 `error_kind`、`repo` 用 `status`+`error`；本 change 只认 `error_kind`，故
  **将来新加的 service 若发明第三种约定，信号会再次漏**。这是已知的、被接受的缺口。
- **Q2（`--since` 时区）**：定为只收带时区的 ISO 串，见上。
- **Q3（信号分类计数摘要）**：已做（task 5.5）。打到 stderr 而非 stdout——缺省模式下
  stdout 是草稿 JSON 本身，摘要混进去会破坏 `triage scan > draft.json` 这种用法。
