## 1. 持久层：按 id 取未覆盖原文

- [x] 1.1 `db/repositories/conversation_repository.py` 新增 `get_turns_after(session_id, after_id)`：`WHERE session_id=? AND id > after_id ORDER BY id ASC`，复用 `session_scope`，不改既有方法
- [x] 1.2 单测：写入若干回合 → `get_turns_after(after_id=0)` 返回全部、`after_id=中间值` 只返回其后、`after_id=最大` 返回空

## 2. 摘要记忆：读侧组装方法

- [x] 2.1 `harness/memory/summary.py` 的 `LLMSummaryMemory` 新增 `get_read_context(session_id) -> (summary_text, uncovered_turns)`：读摘要缓存得 `(summary_text, covered_upto)`（无则 `"" , 0`），再经 `conversations_repo.get_turns_after(session_id, covered_upto)` 取未覆盖原文回合返回。保持 `SummaryMemory` 协议、`NoOpSummary`、`summarize`/`get_summary_hint`/`compact_if_needed` 不变
- [x] 2.2 容错：摘要缓存读失败按无摘要处理（covered_upto=0）；方法自身不抛（异常交由 handler 兜底）
- [x] 2.3 单测（fake repo）：无摘要→返回全部原文；有摘要(covered_upto=k)→summary_text + 仅 id>k 的原文；已覆盖回合原文不重复

## 3. 编排接入：读侧切换 + 兜底

- [x] 3.1 `api/chat_handler.py` 读侧主路径改为 `get_read_context(sid)`：摘要作独立 `SystemMessage` 置 history 首条，其后接 `id>covered_upto` 原文（升序），再接本轮用户输入
- [x] 3.2 兜底：`get_read_context` / repo 读异常时退回旧行为（`session.history` + `ShortTermMemory` 截断 + `get_summary_hint`），记 warning，不崩
- [x] 3.3 顺序确认：系统提示 → 摘要 → 未覆盖原文 → 当前用户输入；写侧 `compact_if_needed` 与触发逻辑不动

## 4. 测试与验证

- [x] 4.1 新增「夹缝期精确旧细节召回」用例：构造 covered_upto < 某 id ≤ 窗口边界的回合，断言**修复后**该回合原文出现在注入上下文（对照旧逻辑：不出现）
- [x] 4.2 无盲区不变量测试：任取一条历史回合，断言它要么在摘要覆盖内、要么以原文注入（不存在两者皆无）
- [x] 4.3 更新既有 `tests/test_chat_handler_e2e.py` 中受读侧改动影响的注入断言
- [x] 4.4 跑 `uv run pytest`：change 相关 37 项全绿；全量 1 项失败为既有 flaky 真 LLM 测试（test_appointment_agent 自然语言抽取，与本 change 无关，重试即过）
- [x] 4.5 更新 `docs/harness-code-reading.md` §3.4 ②：把「夹缝盲区」从已知限制改为「已修复——可见性分界=covered_upto」，并相应调整流程图说明（夹缝改为「以原文注入」）
