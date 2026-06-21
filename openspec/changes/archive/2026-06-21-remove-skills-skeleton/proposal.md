## Why

Phase 7 留下的 harness `Skill` 骨架（`harness/skills/` 下的 frozen dataclass `Skill` + `SkillRegistry`，纯文本 `content` + 关键词子串匹配）**从未接入任何运行路径**——`chat_handler` / `AgentLoop` / `SubAgent.run` / `delegate` 一处都没调用它，也没有任何具体 Skill 实例或 `build_default_skill_registry`。它是非生产级的「教学影子版」，对未来真正要做的 Agent Skill（`SKILL.md` 开放标准 + 模型驱动加载）几乎零代码复用（缺 frontmatter 校验 / 三级渐进披露 / 资源加载 / 模型驱动选择，全是另起炉灶）。按 YAGNI 在生产化阶段移除死代码，结论详见 [docs/skills-notes.md](../../../docs/skills-notes.md) §8；git 历史留底，将来真撞上「SOP/话术库膨胀 + 运营自助」需求时按开放标准重做，不复活关键词版。

## What Changes

- **移除 harness `Skill` 骨架**：删除整个 `harness/skills/` 目录（`base.py` / `registry.py` / `__init__.py`）。
- **移除其单测**：删除 `tests/test_skills.py`。
- **移除 `skills` capability spec**：删除 `openspec/specs/skills/spec.md`（本期 delta 用 REMOVED 标注）。
- **清理文档性引用**：清理 `harness/subagents/` 等处仅出现在注释/docstring 里的「Skills 化」措辞（无代码依赖），使描述与「skills 已移除」一致。
- 非破坏性：因 skills 从未在运行路径中被引用，删除后对外行为（API / 前端 / 子 Agent / delegate）完全不变。

## Capabilities

### New Capabilities
<!-- 无新增能力 -->

### Modified Capabilities
- `skills`: **REMOVED**——整个 skills 能力（Skill 声明结构 + SkillRegistry 按需加载）从规格中移除；该能力从未落入运行路径，YAGNI 删除。

## Impact

- **删除代码**：`harness/skills/`（整目录，~106 行）、`tests/test_skills.py`（~63 行）。
- **删除规格**：`openspec/specs/skills/spec.md`。
- **文档微调**：`harness/subagents/__init__.py`、`harness/subagents/base.py` 中提及 Skills 的注释/docstring。
- **不碰**：`services/`、`db/`、`config/model_provider.py`、RAG（SQLite+FAISS）、子 Agent / `delegate` 运行路径——它们均不依赖 skills，删除后行为不变。
- **验证**：`uv run pytest` 须绿（删 `test_skills.py` 后其余测试不受影响）；`evals/` 端到端通过率不回归。
