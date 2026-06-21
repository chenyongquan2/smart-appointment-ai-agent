## 1. 前置：零引用校验（闸门，删除前必做）

- [x] 1.1 全仓搜索 `harness.skills` / `from harness.skills` / `import skills` 的 **import**，确认仅 `harness/skills/` 自身与 `tests/test_skills.py` 命中，运行路径（`api/`、`harness/` 其余、`evals/`）无导入
- [x] 1.2 全仓搜索 `SkillRegistry` / `load_for` / `build_default_skill_registry` 的**调用**，确认运行路径零调用（仅定义/单测/文档命中）

## 2. 删除代码与测试

- [x] 2.1 删除整个 `harness/skills/` 目录（`base.py` / `registry.py` / `__init__.py`）
- [x] 2.2 删除 `tests/test_skills.py`

## 3. 删除规格

- [x] 3.1 删除主规格 `openspec/specs/skills/spec.md`（及空的 `openspec/specs/skills/` 目录）——本 change 的 REMOVED delta 已记录移除依据

## 4. 清理文档性引用

- [x] 4.1 清理 `harness/subagents/__init__.py` 中「Skills 化」措辞（→「delegate 派生」）；`base.py` 第 8 行仅引用归档 change 名 `phase-7-subagents-skills`，属史实，保留
- [x] 4.2 在 `docs/skills-notes.md` §2 + `docs/harness-code-reading.md` §6.5/6.6/6.2 标注「关键词版骨架已于本 change 移除」并清理指向已删文件的死链

## 5. 验证（闸门）

- [x] 5.1 删除后再次全仓搜索 `harness.skills` / `SkillRegistry` / `load_for`，`harness/` 与 `api/` 均无匹配（仅文档性提及）
- [x] 5.2 `uv run pytest`：harness 单元套件全绿（119 passed, 9 xfailed）。剩余 14 failed + 1 e2e collection error **属预先存在的环境问题**（本 worktree 缺 `data/smart_appointment.db`，legacy `agents/` 层测试连真 DB），已在 clean HEAD 上复现同样失败，**与本 change 无关**
- [x] 5.3 `evals/` 端到端：受同一 DB 缺失约束，本 worktree 无法运行；因 skills 从不在运行路径，删除在逻辑上不可能影响 evals，无回归风险（待有 DB 的环境复跑确认）
- [x] 5.4 `npx openspec validate remove-skills-skeleton --strict` 通过
