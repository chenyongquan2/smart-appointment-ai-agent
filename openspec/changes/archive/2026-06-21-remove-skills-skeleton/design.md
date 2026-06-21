## Context

Phase 7（`2026-06-09-phase-7-subagents-skills`）落地了子 Agent / delegate 派生，同时**附带**留下了一个 `skills` 能力骨架作为「扩展点」。现状（全仓库搜索确认）：

- `Skill` / `SkillRegistry` / `load_for` 仅出现在 `harness/skills/`（定义）、`tests/test_skills.py`（单测）、`openspec/specs/skills/spec.md`（规格）、以及若干文档/注释。
- 运行路径 `api/chat_handler.py` → `AgentLoop` → `SubAgent.run` → `delegate` **一处都不导入、不调用** skills；没有任何具体 Skill 实例，也没有 `build_default_skill_registry`。

因此这是一次**纯删除（死代码清理）**，不涉及行为变更或迁移复杂度。design.md 仅用于固化「为何删而非进化」「如何确认零引用」两点决策。

## Goals / Non-Goals

**Goals:**
- 删除从未接入的 harness `Skill` 骨架及其单测、规格，消除误导性「扩展点」。
- 删除后 `uv run pytest` 全绿、`evals/` 不回归，对外行为零变化。
- 文档与代码注释和「skills 已移除」保持一致。

**Non-Goals:**
- 不引入任何替代的 skill 机制（不上 `skills-ref` / Deep Agents / `SKILL.md`）——那是「真撞上 SOP 膨胀需求」时的将来工作。
- 不动子 Agent / delegate / RAG / services / db 等任何运行路径资产。

## Decisions

**D1：删除而非「进化」关键词版骨架。**
- 选择：整体删除 `harness/skills/`。
- 理由：真正的生产级渐进披露需要 `SKILL.md` frontmatter 校验 / 三级披露 / 资源加载 / 模型驱动选择，关键词版骨架一个都没有，「进化」等于重写 `skills-ref`/Deep Agents 已做好的东西并偏离开放标准。能继承的只有「理念」，不是代码。
- 备选：保留并标注 `@deprecated`——否决，死代码继续误导读者以为有 skill 能力，违背 YAGNI。

**D2：删除前以零引用为前置闸门。**
- 实施：在删除任务前用 grep 确认 `harness/skills`、`Skill`、`SkillRegistry`、`load_for` 在运行路径（`api/`、`harness/` 除 `skills/` 自身）无 import/调用，仅剩文档性提及；删除后再次全仓搜索复核无悬挂引用。
- 理由：把「非破坏性」从论断变成可验证步骤。

**D3：规格用 REMOVED delta + 归档同步。**
- `openspec/changes/remove-skills-skeleton/specs/skills/spec.md` 以 `## REMOVED Requirements` 标注两条需求（带 Reason/Migration）；归档时 `openspec/specs/skills/` 随之移除。

## Risks / Trade-offs

- [删除遗漏悬挂引用导致 import 报错] → D2 的删除后全仓搜索 + `uv run pytest` 双重兜底；CI/本地测试会立刻暴露。
- [将来真需要 skill 时「无现成代码」] → 已在 docs/skills-notes.md §6–8 论证：该骨架对生产版零复用，git 历史留底即可，按开放标准重做才是正路。
- [文档残留旧措辞造成认知偏差] → 任务包含清理 `subagents/` 注释及在 skills-notes 留删除记录（或由本 change 归档记录承载）。

## Migration Plan

无运行时迁移。步骤：① 零引用校验 → ② 删除代码/测试/规格 → ③ 清理文档性引用 → ④ `uv run pytest` 绿 + evals 不回归 → ⑤ `/opsx:archive` 同步主规格移除 `skills`。回滚：`git revert` 本 change 即可恢复骨架（历史留底）。
