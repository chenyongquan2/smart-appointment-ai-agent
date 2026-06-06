## Context

本变更是重构 [plan](../../../docs/harness-refactor-plan.md) 的 **Phase 0**——在把 `agents/` 改成 `harness/` 之前先建回归安全网。被测对象是现有意图分类器 [task_classifier.py](../../../agents/task_classification/task_classifier.py),它经 LLM 输出 5 类:`appointment` / `query` / `pay` / `statistics` / `other`(`classify_task` 用 `strip().lower()` + 白名单兜底,异常时返回 `other`)。现有 `evals/` 仅为骨架且用例口径不符。

## Goals / Non-Goals

**Goals:**
- `cases.jsonl` 校准到真实 5 类、扩到 ~20 条,覆盖 5 类 + 边界。
- `run_evals.py` 接入真实分类器,逐条比对 `expected_intent`,输出**总准确率 + 按类目分项 + 错误清单**。
- 一键 `uv run python evals/run_evals.py` 产出可复跑的基线。

**Non-Goals:**
- 工具调用准确率(等 Phase 2 工具层就绪)。
- 改进/重写分类器本身(那是 Phase 1)。
- JSON logging trace(plan Phase 0 的另一子项,拆到单独 change)。
- 多次采样消除 LLM 抖动(本次记单次基线即可)。

## Decisions

- **用真实 `TaskClassifier` 跑基线(经 `config/model_provider`),不 mock**。理由:基线必须反映系统真实表现;mock 失去意义。代价:需 API key、有调用成本。
- **`expected_intent` 采用分类器的 5 类口径**,不用 `constants.py` 的 `StateEnum`(4 类:classify/appointment/consult/other)。理由:分类器是被测对象,基线要对齐它的输出空间。代码里两套口径不一致的问题记录在案,留待后续统一。
- **`expected_tools` 保留为前瞻注解、不计分**。理由:工具 Phase 2 才存在;现在评分会全错。Phase 2 起启用工具调用评分。
- **运行器对缺 API key 优雅降级**:检测不到可用模型时打印清晰提示并以非零码退出,**不抛栈崩溃**。
- **输出"成功静默、只详列错误"**:总览一行(准确率 N/총),错误条目逐条列(输入 / 期望 / 实际),对齐 project.md 的验证准则。
- **用例格式延续 `jsonl` + `//` 注释**:已有、低门槛、人可读可手改。

## Risks / Trade-offs

- **LLM 成本/延迟(~20 次调用)** → 用例数控制在 ~20;运行器支持 `--limit N` 做快速冒烟。
- **LLM 非确定性致基线波动** → 基线标注为"单次快照、非确定";需要稳定对照时再考虑固定随机性/多次平均(本次不做)。
- **分类器异常兜底为 `other`** → 错误清单需能区分"判错"与"异常降级"(运行器可在捕获异常时单独标注),避免基线误读。
- **API key 缺失致跑不出基线** → 优雅提示;同时保留骨架的"仅加载校验用例"模式作为无 key 时的退路。
