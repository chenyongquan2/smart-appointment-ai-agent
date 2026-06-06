# evals/ — 重构回归评估集（Phase 0）

> 开发期 harness 的**验证回路**核心。用例集贯穿整个重构;**评分指标随阶段演进**(见下方 ⚠️)。
> 配套：[../docs/harness-refactor-plan.md](../docs/harness-refactor-plan.md) 的 Phase 0。

> ⚠️ **用例集长期复用，但"评分指标"随阶段演进——别把意图准确率当永久指标。**
> - **Phase 1–2（分类器仍在）**：意图分类准确率是**有效的退化对照**(Phase 1 结构化输出正是要改进它,验收口径就是分类错误率)。
> - **Phase 3 ReAct/TAO 起**：意图分类并入 loop(意图隐含在"调了哪些工具"里)，评分改用**工具调用准确率 → 端到端结果（约对没约对）**(见 `expected_tools`；plan 的 Phase 3 验收口径也是"端到端通过率≥基线")。
> 耐用资产是**这批行为级用例 + 运行器框架**(与实现解耦)，而非某个准确率数字本身。

## 这是什么

一套**可复用的行为评估用例集 + 运行框架**——以 `输入 → 期望行为` 为用例，在把 `agents/` 重构为 `harness/` 的过程中**客观衡量**系统行为有没有退化，而不是靠"感觉还行"。用例集是**耐用资产**；评分模式随阶段演进（见上方 ⚠️）。

## 意图口径（5 类）

`expected_intent` 取自真实分类器 [../agents/task_classification/task_classifier.py](../agents/task_classification/task_classifier.py) 的输出空间：

| 意图 | 含义 |
|------|------|
| `appointment` | 预约任务（用户预约 / 工作人员告知延长服务等） |
| `query` | 查询任务（咨询价格、项目、技师、位置等） |
| `pay` | 支付任务（已选定技师/项目，待支付） |
| `statistics` | 统计任务（工作人员上报已完成） |
| `other` | 与按摩服务无关 |

> 注意：`config/constants.py` 的 `StateEnum` 是另一套 4 类口径（classify/appointment/consult/other），与分类器不一致。评估以**分类器的 5 类**为准；统一二者留待后续。

## 文件

- `cases.jsonl` — 评估用例（一行一条 JSON；`//` 开头为注释，运行时跳过）。
- `run_evals.py` — 运行器：接入真实 `TaskClassifier`，逐条比对 `expected_intent`，输出准确率基线 + 按类目分项 + 错误清单。

## 用例格式

```json
{"input": "我想预约明天下午的按摩", "expected_intent": "appointment", "expected_tools": ["find_technician", "check_availability"]}
```

- `expected_tools` 是 **Phase 2 工具层的前瞻注解，当前不计分**（工具尚不存在）。工具调用准确率待 Phase 2 启用。

## 运行

```bash
uv run python evals/run_evals.py            # 全量, 输出意图准确率基线
uv run python evals/run_evals.py --limit 5  # 冒烟, 只跑前 5 条
```

- 产出基线需 **API key 可用**（`.env` 里配好 `MODEL_PROVIDER` 对应的 `*_API_KEY`）。
- 无 key 时运行器**优雅降级**：打印用例清单 + 提示，并以非零码退出，不崩。

## 关于意图准确率（当前评分模式）

- 它是**一次性运行记录、非永久"基线"**，且**非确定性**（LLM 有随机性，即便 temperature=0 也可能微抖）。需要稳定对照时再考虑多次平均。
- 当前分类器用 `strip().lower()` + 白名单兜底，异常时降级为 `other`——这个数字会如实反映其表现，**正是 Phase 1（结构化输出）要改进的对象**。

## 后续（Phase 1+ 落地时）

- [ ] Phase 1 结构化输出改造后，重跑本评估集，确认意图准确率不低于基线（此阶段分类器仍在，指标可比）。
- [ ] Phase 2 工具层就绪后，把 `expected_tools` 纳入评分（工具调用准确率）。
- [ ] Phase 3 ReAct loop 后，意图指标退场，改用端到端通过率（plan Phase 3 验收口径）。
- [ ] 把"跑 evals"接入 `/phase` 的验证闸门（闸门 2）。
