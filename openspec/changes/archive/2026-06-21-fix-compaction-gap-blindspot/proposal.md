## Why

记忆压缩当前读侧注入 = 摘要(id ≤ `covered_upto`) + 最近 `window_turns` 条原文。落在**夹缝**（`covered_upto` < id ≤ 窗口边界：已掉出窗口、但尚未被压缩）的回合，**既不在窗内原文、又不在摘要里** → 在「掉出窗口」到「下次压缩」之间对 LLM 暂时不可见。

这是个有界但真实的盲区（峰值 ≈ `min_old_turns` 条、几回合），且与「压缩是为了不丢窗外信息」的初衷相悖。失效例：用户 11 轮前说「周六 14:30」，13 轮时刚滑出窗口、还没触发压缩，此时说「提前一小时」——LLM 手里既无该原文也无摘要，可能答错。

## What Changes

- **读侧可见性分界改为 `covered_upto`**：注入 = 摘要(id ≤ `covered_upto`) + **id > `covered_upto` 的全部回合原文**。没进摘要的一律保留原文 → **彻底消除夹缝盲区**。
- **`window_turns` 语义收窄**：从「读侧可见性上限」退化为「只决定压缩节奏（写侧何时触发压缩）」。读侧不再用固定窗口截断 verbatim。
- 读侧改从 `conversations` 仓库取 **id-bearing** 历史并按 `covered_upto` 过滤（in-memory `Turn` 不带 id，无法过滤）；新增/复用仓库读取「`after_id` 之后的回合」。
- 摘要文本仍作独立 `SystemMessage` 置于 history 首条；写侧 `compact_if_needed` 与触发逻辑**不变**。
- 保持 `SummaryMemory` 接口与 `NoOpSummary` 不破坏；补「夹缝期精确旧细节召回」回归用例。

## Capabilities

### New Capabilities
<!-- 无新增独立能力 -->

### Modified Capabilities
- `session-memory`: 「摘要记忆层（生产级压缩）」与「短期对话记忆窗口」两条需求的**读侧可见性**行为变更——可见性分界由「最近 N 条窗口」改为 `covered_upto`（未被摘要覆盖的回合一律以原文注入，消除夹缝盲区）；`window_turns` 改为只约束压缩触发节奏。

## Impact

- **代码**：
  - `api/chat_handler.py`：读侧组装改为「摘要 + id > covered_upto 原文」。
  - `harness/memory/summary.py`：新增读侧方法返回 `(summary_text, covered_upto)`（或等价），供编排层取未覆盖原文。
  - `db/repositories/conversation_repository.py`：可加 `get_turns_after(session_id, after_id)`（或读侧用既有 `get_turns` 再过滤）。
  - `harness/memory/short_term.py`：窗口语义收窄说明；读侧可能不再用其截断 verbatim（保留类、保向后兼容）。
- **不动**：`SummaryMemory` 接口、`NoOpSummary`、写侧 `compact_if_needed` 与触发阈值、`ConversationSummary` 表结构、`services/`、RAG。
- **成本**：读侧多一次按 `session_id`（已建索引）的 SQLite 读 + 多注入夹缝那几条 token（有界，≈ `window_turns + min_old_turns` 上界）。
- **风险**：无摘要时 uncovered = 全部历史，但首次压缩前历史长度有上界（≈ `window_turns + min_old_turns`），不会无界膨胀。
