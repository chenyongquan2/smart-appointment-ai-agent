## ADDED Requirements

### Requirement: 评估用例集对齐真实意图口径

评估集 `evals/cases.jsonl` SHALL 以 `输入 → 期望意图` 为用例,且 `expected_intent` MUST 取自真实分类器的 5 类口径之一:`appointment`、`query`、`pay`、`statistics`、`other`。用例集 SHALL 覆盖全部 5 类,并包含边界场景(多槽位、缺槽位追问、改约、与服务无关的输入),总量 SHALL 不少于 18 条。

#### Scenario: 用例意图取值合法

- **WHEN** 加载 `cases.jsonl` 中任一非注释用例
- **THEN** 其 `expected_intent` 必须是 `{appointment, query, pay, statistics, other}` 之一,否则运行器报错并指出行号

#### Scenario: 五类全覆盖

- **WHEN** 统计用例集的 `expected_intent` 分布
- **THEN** 5 个类目每个至少出现一次

#### Scenario: 注释与空行被跳过

- **WHEN** 文件含 `//` 开头的注释行或空行
- **THEN** 运行器加载时跳过它们,不计入用例

### Requirement: 意图分类准确率基线

运行器 `evals/run_evals.py` SHALL 经 `config/model_provider` 实例化真实 `TaskClassifier`,对每条用例执行 `classify_task`,将结果与 `expected_intent` 比对,并 SHALL 输出总准确率、按类目分项准确率,以及逐条错误清单(输入 / 期望 / 实际)。通过的用例 SHALL NOT 逐条打印(成功静默)。

#### Scenario: 产出基线

- **WHEN** 在 API key 可用时运行 `uv run python evals/run_evals.py`
- **THEN** 输出形如"意图准确率 X/N (P%)"的总览,并仅详列判错的用例

#### Scenario: 缺少 API key 时优雅降级

- **WHEN** 运行时检测不到可用模型/API key
- **THEN** 运行器打印清晰提示并以非零退出码结束,不抛出未捕获异常崩溃

### Requirement: 工具调用为前瞻注解

用例 MAY 携带 `expected_tools` 字段作为 Phase 2 的前瞻注解,但本能力的基线评分 SHALL NOT 将其计入(工具层尚不存在)。

#### Scenario: expected_tools 不影响基线

- **WHEN** 计算意图准确率基线
- **THEN** `expected_tools` 字段被忽略,不参与判定对错
