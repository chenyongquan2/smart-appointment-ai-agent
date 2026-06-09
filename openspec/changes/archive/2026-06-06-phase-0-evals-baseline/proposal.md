## Why

重构 `agents/` → `harness/` 之前必须先有**回归安全网**,否则无法客观判断改动是否让"意图识别"退化(plan 要求 Phase 0 先于 Phase 1)。当前 `evals/` 只是骨架,且种子用例的 `expected_intent` 与真实分类器**不一致**(用了 `consultation`,而真实分类器输出 `query`,且漏了 `pay`/`statistics`),运行器也没接真实分类器、出不了基线。本变更把评估集校准到真实代码并产出意图分类准确率基线,作为 **Phase 1(结构化输出)** 的退化对照起点——该指标在 Phase 3 ReAct loop 后会让位于工具调用 / 端到端通过率。

## What Changes

- **校准 `evals/cases.jsonl`**:`expected_intent` 改用真实 5 类枚举——`appointment` / `query` / `pay` / `statistics` / `other`(来源:[task_classifier.py](../../../agents/task_classification/task_classifier.py));扩充到 ~20 条,覆盖 5 类 + 边界(多槽位、缺槽位追问、改约、无关输入)。
- **`evals/run_evals.py` 接入真实分类器**:经 `config/model_provider` 实例化 `TaskClassifier`,对每条用例跑 `classify_task`,与 `expected_intent` 比对,输出**意图分类准确率基线 + 逐条错误清单**(成功静默、只详列错误)。
- **`expected_tools` 暂作前瞻注解**:`find_technician`/`create_appointment` 等是 Phase 2 才建的工具,本次**不计分**;待工具层就绪后再纳入评分。
- **更新 `evals/README.md`**:记录真实 5 类口径、运行方式、基线含义。

## Capabilities

### New Capabilities
- `eval-harness`: **可复用的行为用例集 + 评估运行框架**(头号交付物,贯穿整个重构)。评分模式随阶段演进——Phase 1–2(分类器仍在)按意图分类准确率计分,Phase 3 ReAct loop 起意图并入循环,改用工具调用 / 端到端通过率(见 `expected_tools`)。意图准确率是**当前(Phase 1–2)的评分模式,非永久指标**;本次顺带产出一次,作为 Phase 1 的对照起点。

### Modified Capabilities
<!-- 无:本变更不修改任何已有 spec 的需求 -->

## Impact

- **改动文件**:`evals/cases.jsonl`、`evals/run_evals.py`、`evals/README.md`;另含 `pyproject.toml` 一处 pytest 配置(`pythonpath=["."]`,使测试可被收集——契合 Phase 0"跑通 tests/"目标)。
- **验证副产物**:pytest 收集修复后暴露出 `agents/` 层 21 个**预存失败**(缺 `pytest-asyncio` 配置 + `user_behavior` 的 dict 入库 bug),与本改动无关、且该层将被重构替换,**另开 change 跟踪**。
- **运行依赖**:产出基线需调用 LLM(`config/model_provider` 的 API key 必须可用);无 key 时运行器应给出清晰提示而非崩溃。
- **不触碰**:`services/`、`db/`、`config/model_provider.py`、RAG、`agents/` 源码(只读引用其类目枚举,不修改)。
- **风险**:LLM 调用有成本/延迟(~20 次);分类器当前用 `strip().lower()` + 白名单兜底,基线会反映其真实表现(这正是后续 Phase 1 结构化输出要改进的对象)。
