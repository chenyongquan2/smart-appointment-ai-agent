# 退役旧意图分类器 + 门禁改守 2 项

## Why

旧意图分类器（`agents/task_classification/`）在 harness 重构后已退出主服务链路（TAO 循环靠工具选择路由，不经过它），但仍以三种形态残留：注册在路由表的 `api/task.py` 端点、evals 每次真调它算"意图分类准确率"（且该指标在 `GATED_METRICS` 门禁中）、一个专属测试文件。**门禁正在守护一个不服务任何用户的组件**——它绿或红都不反映系统好坏；harness 架构下"意图理解"已由工具选择体现，被工具级指标（name 级 F1）完整覆盖，再算一个意图指标是同一信号算两遍。跨代对照的历史使命（重构期证明无退化）已随重构归档而完成。

## What Changes

- **删除**旧分类器组件：`agents/task_classification/`、`agents/task_classification_agent.py`（及 `agents/__init__.py` 导出）
- **删除** `api/task.py` 分类端点及其路由注册（实现时先 grep 前端/模板确认无调用方）
- **删除** `tests/test_task_classification_agent.py`，更新 `tests/conftest.py` 中的模块引用
- **evals 改造**：
  - `run_evals.py` 摘除分类器实例化与调用（含多轮用例"首轮意图判定"路径）
  - `metrics.py` 移除 `intent_accuracy`；**BREAKING**：`GATED_METRICS` 从 3 项改为 2 项 `{工具调用-F1, 槽位抽取完整率}`
  - "端到端延迟"指标改口径：原实测为分类器单次调用耗时（随组件退役失去来源），改计端到端真跑耗时（该指标本不在门禁，无回归判定影响）
  - `baseline.json` 重定（`--update-baseline --samples 3`）
- **保留**：`cases.jsonl` 的 `expected_intent` 标签及其校验/覆盖规则——它是数据集构成元数据（5 类覆盖、每类下限、held-out 覆盖规则都依赖它），退役的只是"跑分类器算准确率"这件事

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `intent-classification`: 整个能力退役——两条需求（结构化输出枚举分类、异常安全降级）REMOVED，能力对应组件删除
- `eval-harness`: 移除"意图分类准确率基线"需求；门禁需求的 `GATED_METRICS` 从 3 项改 2 项；用例集需求中 `expected_intent` 口径从"真实分类器口径"改为"数据集意图标签口径"；多指标报告、工具调用注解、多轮评估需求中涉及意图判定的条款相应修订；延迟指标口径改为端到端真跑耗时

## Impact

- 删除：`agents/task_classification/`（3 文件）、`agents/task_classification_agent.py`、`api/task.py`、`tests/test_task_classification_agent.py`
- 修改：`agents/__init__.py`、`api/__init__.py`、`tests/conftest.py`、`evals/run_evals.py`、`evals/metrics.py`、`evals/baseline.json`（重定）、`evals/README.md`
- 无新增依赖；`cases.jsonl` 不改动
- 验证：`uv run pytest` 全绿；`--update-baseline --samples 3` 重定基线后 `--gate` 以退出码 0 通过（实守 2 项）
