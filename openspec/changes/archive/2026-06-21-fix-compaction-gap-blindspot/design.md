## Context

记忆压缩（change `add-context-compaction`）读侧组装 = 摘要(id ≤ `covered_upto`) + `ShortTermMemory` 取的最近 `window_turns` 条原文（[chat_handler.py:109-117](../../../api/chat_handler.py)）。**夹缝**（covered_upto < id ≤ 窗口边界）的回合两边都不在 → 短暂不可见。详见上一题客观分析。

约束（CLAUDE.md / project.md）：保持 `SummaryMemory` 接口与 `NoOpSummary` 不破坏；最小改动、向后兼容；改动相关 `uv run pytest` 必须绿。in-memory `Turn`（[session.py:19](../../../harness/runtime/session.py)）只有 role/content、**不带 id**，而本修复的可见性分界需要 turn id。

## Goals / Non-Goals

**Goals:**
- 消除夹缝盲区：每条回合要么以摘要、要么以原文出现在上下文中，分界为 `covered_upto`。
- `window_turns` 收窄为「只管压缩触发节奏」，不再当读侧可见性上限。
- 失败有兜底（repo 读失败时退回旧行为），保持健壮与向后兼容。

**Non-Goals:**
- 不改写侧 `compact_if_needed`、触发阈值、`ConversationSummary` 表结构。
- 不改 `SummaryMemory` 协议与 `NoOpSummary`。
- 不引入向量检索/语义召回（超范围）。

## Decisions

### D1 — 可见性分界改为 `covered_upto`，读侧从持久层取 id-bearing 历史
读侧组装改为：`summary(id ≤ covered_upto)` + `原文(id > covered_upto)`。因 in-memory `Turn` 无 id，未覆盖原文从 `ConversationRepository` 读（id 稳定、单调）。
- *为何*：covered_upto 是唯一能把「已压/未压」精确分界的游标；用它做可见性边界，逻辑上保证「没进摘要的必有原文」，盲区不可能存在。
- *备选*：给 in-memory `Turn` 加 id → 要改 SessionStore 写入/恢复链路，改动面更大，否决。

### D2 — 在 `LLMSummaryMemory` 加读侧方法 `get_read_context(session_id) -> (summary_text, uncovered_turns)`
它读摘要缓存拿 `(summary_text, covered_upto)`，再经 `conversations_repo` 取 `id > covered_upto` 的原文回合返回。无摘要时 `covered_upto=0`（全部原文）。
- *为何*：`LLMSummaryMemory` 已持有两个 repo，集中读侧逻辑、handler 改动最小；接口签名不变（新增方法，不动 `summarize`/`get_summary_hint`/`compact_if_needed`）。

### D3 — 新增 `ConversationRepository.get_turns_after(session_id, after_id)`
`SELECT ... WHERE session_id=? AND id > after_id ORDER BY id ASC`。复用 `session_scope`，风格对齐既有方法，不改既有方法。
- *为何*：按主键过滤 + 已有 `session_id` 索引，O(log n) 定位，热路径代价可接受。

### D4 — `ShortTermMemory` 保留，降级为兜底路径（向后兼容）
主路径走 `get_read_context`（repo）。若 repo 读异常，handler 退回旧行为：`session.history` + `ShortTermMemory(window_turns)` 截断 + `get_summary_hint`。
- *为何*：`ShortTermMemory` 仍被独立单测覆盖、且作为「持久层抖动时的安全网」有价值；不删类、保兼容。读侧主逻辑切换、但旧路径仍可用。

### D5 — 摘要注入位置不变
摘要文本仍作独立 `SystemMessage` 置于 history 首条；其后是 `id > covered_upto` 的原文（升序）；再之后是本轮用户输入。顺序：系统提示 → 摘要 → 未覆盖原文 → 当前输入。

### D6 — 上下文体量有界
未覆盖原文条数 = `id > covered_upto` 的回合数 = 「自上次压缩以来的窗外积累 + 当前窗内」，上界 ≈ `window_turns + min_old_turns`（再多就触发压缩了）。故读侧 token 不会无界膨胀。

## Risks / Trade-offs

- **热路径多一次 SQLite 读** → 按主键 + session_id 索引，代价小；且与既有 SessionStore 持久化同源。必要时可加内存缓存（本 change 不做）。
- **repo 与 in-memory SessionStore 双源一致性** → 读侧统一以 repo 为准（id 权威）；SessionStore 仍负责 append/restore。当前轮用户输入在读之后才 append，故 repo 在读时不含当前输入，与现有语义一致。
- **无摘要时注入全部历史** → 有上界（D6），不膨胀；超长会话必然已触发压缩、covered_upto 前移。
- **行为变更影响既有 e2e 断言** → 更新相关测试；新增「夹缝期精确旧细节召回」用例（修复前不可见、修复后可见）。

## Migration Plan

1. 加 `ConversationRepository.get_turns_after`（+单测）。
2. 加 `LLMSummaryMemory.get_read_context`（+单测，用 fake repo）。
3. `chat_handler` 读侧切换为主路径 `get_read_context`，repo 异常退回 `ShortTermMemory` 兜底。
4. 更新/新增测试：夹缝召回用例 + e2e 注入断言；`uv run pytest` 全绿。
- **回滚**：handler 读侧切回 `_short_term.to_messages(session.history)` + `get_summary_hint` 即恢复旧行为；新增方法不影响其他路径。

## Open Questions

（无遗留；fallback 与 window 语义已在 D4/D6 定。）
