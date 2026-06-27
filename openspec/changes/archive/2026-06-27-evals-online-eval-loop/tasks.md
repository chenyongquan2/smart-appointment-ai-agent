## 1. 持久化文件 SpanExporter（产 trace）

- [x] 1.1 新建 `harness/observability/file_exporter.py::FileSpanExporter`：`export(span)` 把 `{"event":"span", **span.to_dict()}` 以单行 JSON（`ensure_ascii=False`、`default=str`）追加写目标文件；默认目录 `evals/traces/`，文件名按 trace_id/启动时刻区分。
- [x] 1.2 `export` 内 `try/except` 吞一切 IO 异常、失败仅 `logger.warning`，绝不抛回主循环（对齐 `exporter.py` 协议契约）。
- [x] 1.3 单测（离线）：写临时文件跑一次，断言每行可 `json.loads` 回与 `Span.to_dict()` 一致的结构；注入会抛的伪文件对象，断言 `export` 不抛、仅 warning。

## 2. 生产接线与采样

- [x] 2.1 在 `api/chat_handler.py` 模块级构造 `Tracer(FileSpanExporter(...))`，注入主 `_agent_loop`，并经 `build_delegate_tool(..., tracer=)` 透传子 Agent（对齐 `evals/agent_capture.py` 接法）。
- [x] 2.2 加一层「整条 trace 留/弃」采样封装（`SamplingSpanExporter`）：默认全量；错误信号必留；`sample_rate`（默认 `1.0`，经 `EVAL_TRACE_SAMPLE_RATE` 调）只对非错误 trace 按比例采。采样按整条 trace 决策（按 trace_id 缓冲、root 结束时决断），不在 exporter 内逐 span 判。
- [x] 2.3 烟测：接入后 `ProcessUserInput_stream` 的 `[REPLY]` 流式语义不变 + 真实落出带 user_input/session_id 的 trace（[tests/test_online_trace_wiring.py](../../../tests/test_online_trace_wiring.py)）。`[ERROR]` 前缀属遗留 agents/ 路径、当前 harness loop 不产，已在 trace_signals 诚实标注。

## 3. 半自动 triage 甄别（纯函数）

- [x] 3.1 信号判定 `harness/observability/trace_signals.py::detect_bad_signals`（放 harness 层供采样 exporter 与 triage 复用、不反向依赖）；`evals/triage.py::triage_traces` 按 trace_id 分组调它产候选。纯函数、不触网、不调 LLM。
- [x] 3.2 信号口径严格对齐 `agent_loop.py` 真实落点：error 事件(guardrail_exhausted/spin_detected)、observation 的「工具执行失败」前缀、结构化 max_steps（末步仍调工具且无 error）。复用 `collect_tool_calls` 还原工具序列。`[ERROR]` 前缀属遗留 agents/，诚实排除。
- [x] 3.3 单测（[tests/test_triage.py](../../../tests/test_triage.py)）：各信号 + 干净 trace 不入选；含文件往返与分组还原 input。

## 4. 标注草稿与回灌 cases.jsonl（纯函数 + 人审）

- [x] 4.1 `triage_traces` 还原标注草稿：`input`(取 root span 的 user_input) + `_observed_tools`/`_observed_reply`，expected_* 留空待人填（字段集 = `cases.jsonl` 现有口径 + `source`）。
- [x] 4.2 `append_cases(cases_path, new_cases) -> 报告`：读现有用例（跳 `//` 注释与空行，与 `load_cases` 同口径），`normalize_input` 去重（strip+lower+折叠空白，对齐 metrics `_normalize_arg`），已存在/批内重复跳过并报告；只写 CANONICAL_KEYS + `"source":"online"`，落在 `// --- online 回灌 ---` 分节下。
- [x] 4.3 回灌后**不自动 re-baseline**：CLI 末尾打印提醒「用例集已变更，需 `--update-baseline`」，`baseline.json` 不被改动。
- [x] 4.4 单测（[tests/test_triage.py](../../../tests/test_triage.py)）：新用例带 `source`、可被 `load_existing_inputs` 读到；等价/批内重复跳过且报告；辅助 `_` 字段不入用例集；基线文件未被改。

## 5. CLI 串联（产→采→标→回灌）

- [x] 5.1 `evals/triage.py` 加 `scan`/`append` 两子命令：scan 从 `evals/traces/` 读 trace → 甄别 → 写标注草稿；append 把人工编辑后的草稿去重回灌 + 打印重定基线提醒。退出码/降级风格对齐 `run_evals.py`。
- [x] 5.2 端到端冒烟：造样例 trace → scan → 模拟人工填 expected_* → append，整条 CLI 跑通（rc=0、用例正确落带 `source=online`），无需真 LLM。

## 6. 存储、文档与验证

- [x] 6.1 `.gitignore` 增 `evals/traces/`（运行期产物）。
- [x] 6.2 `evals/README.md`：记在线闭环用法 + 诚实边界（本项目无真实用户，「生产 trace」=开发/手动对话或回放输入）。
- [x] 6.3 `docs/agent-eval-fieldguide.md` §13：改造 7 状态改为已落地 + 路线图/§12 表/概览表同步；补「依赖改造 6、闭环做法、诚实边界」。
- [x] 6.4 闸门 2 验证：`uv run pytest` 全绿（231 passed, 9 xfailed）；`uv run python evals/run_evals.py --gate` PASS（exit 0，意图 82.5%→90.5%、工具 F1 稳定，槽位本次 N/A 按 skipped、实守 2 项）。
