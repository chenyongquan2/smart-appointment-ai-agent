## 1. 校准用例集

- [x] 1.1 确认真实类目口径:`appointment` / `query` / `pay` / `statistics` / `other`(来源 `task_classifier.py`)
- [x] 1.2 重写 `evals/cases.jsonl`:`expected_intent` 改用 5 类;扩到 20 条,5 类全覆盖 + 边界(多槽位、缺槽位追问、改约、无关输入)
- [x] 1.3 自检:每条 `expected_intent` 合法、5 类各至少 1 条、注释/空行能被跳过

## 2. 运行器接入真实分类器

- [x] 2.1 在 `evals/run_evals.py` 经 `config/model_provider` 实例化 `TaskClassifier`(并修 sys.path 使可 import)
- [x] 2.2 对每条用例 `await classify_task`,异常时单独标注
- [x] 2.3 比对 `expected_intent`,统计总准确率 + 按类目分项准确率
- [x] 2.4 输出:通过用例不打印(成功静默);逐条列出判错(输入 / 期望 / 实际)
- [x] 2.5 缺 API key 优雅降级:打印提示 + 非零退出码,不崩;保留"仅加载校验用例"退路
- [x] 2.6 支持 `--limit N` 做快速冒烟

## 3. 文档与验证

- [x] 3.1 更新 `evals/README.md`:5 类口径、运行方式、指标随阶段演进、`expected_tools` 前瞻说明
- [x] 3.2 修 `pyproject.toml` pytest `pythonpath`,使测试可被收集;**agent 测试的 async 配置缺失 + user_behavior DB bug 为预存债,另开 change 处理**(详见验证结果)
- [x] 3.3 `uv run python evals/run_evals.py` 产出意图准确率(一次性运行记录)
- [x] 3.4 `openspec validate phase-0-evals-baseline` 通过

## 4. 验证结果(一次性运行记录)

- **意图准确率(一次性运行记录,非永久基线):19/20 (95.0%)**
  - appointment 5/6 · query 5/5 · pay 3/3 · statistics 3/3 · other 3/3
  - 唯一判错:`"约个李师傅，他这周六有空吗"` 期望 `appointment`,实际 `query`(模型把"有空吗"当查询;Phase 1 结构化输出的改进目标)
- **pytest**:`pythonpath` 修复后测试可收集;evals 运行器路径(改动相关)正常。`agents/` 层 21 个失败为预存债(async 未配 + user_behavior dict 入库 bug),与本改动无关、且该层将被重构替换,另行跟踪。
