---
name: "Phase: plan-driven SDD development"
description: 取 harness-refactor-plan.md 里的某个 Phase，按 OpenSpec SDD 方式开发实现，带人审与验证两道闸门。
---

把重构路线图里的**一个 Phase**，通过 OpenSpec SDD 工作流落地，全程有两道**强制闸门**。

**输入**：`/phase` 后的参数是 Phase 编号（如 `1`）或 `next`。若没给，先问用户做哪个 Phase。

**步骤**

1. **定位 Phase**
   - 读 `docs/harness-refactor-plan.md`，找到对应 Phase 的小节（如 "Phase 1"）。
   - 若参数是 `next`：跑 `openspec list`，挑出**还没有 active/archived change**的、编号最小的 Phase。
   - 读 `openspec/project.md` 的黄金准则——它是所有 artifact 的约束。
   - 向用户**复述**该 Phase 的：目标、要改的文件、验收标准。确认是这个 Phase 再继续。

2. **Propose（创建 OpenSpec change）**
   - 取一个 kebab-case 变更名：`phase-<N>-<短slug>`（如 `phase-1-structured-output`）。
   - 用 **openspec-propose** skill 创建 change 并生成 `proposal.md` / `design.md` / `tasks.md`。
   - 用该 Phase 在 plan 里的内容（目标/文件/验收）作种子，并以 project.md 的黄金准则为约束。

3. **⏸ 闸门 1 —— 人审（不可跳过）**
   - 把生成的 `proposal/design/tasks` 呈现给用户。
   - 用 **AskUserQuestion** 工具请求**明确批准**后才实现。
   - 用户要改就更新 artifact 再呈现。**未批准不得进入 apply。**

4. **Apply（实现）**
   - 批准后，用 **openspec-apply-change** skill 按 `tasks.md` 实现。

5. **⏸ 闸门 2 —— 验证（不可跳过）**
   - 跑 `uv run pytest`。
   - 回归门禁（改造 6）：若 `evals/baseline.json` 存在，跑 `uv run python evals/run_evals.py --gate`，按退出码判定——
     - `3`（检测到回归）→ **阻断归档**，先报告并修复；
     - `2`（无 API key 优雅降级）或 `1`（缺基线）→ 视为**跳过/警告**，不阻断（门禁是有 key 时尽力跑的纪律，非硬依赖）；
     - `0` → 通过。
   - **成功静默、只报失败。** 任何失败先报告并修复，**不得带病归档**。
   - 核对第 1 步那条 Phase 的**验收标准**是否达成。

6. **Archive（归档）**
   - 绿灯 + 用户确认后，用 **openspec-archive-change** skill 归档并更新 specs。

7. **收尾**
   - 总结：实现了什么、测试/评估结果、下一个 Phase 是哪个。

**护栏**
- **闸门 1 批准前，绝不实现。**
- **闸门 2 通过前，绝不归档。**
- 改动严格限定在该 Phase；**不要碰** project.md 里"不要重写"的保留资产。
- 一个 Phase = 一个 OpenSpec change。
