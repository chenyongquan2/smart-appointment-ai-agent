## MODIFIED Requirements

### Requirement: 评估用例集对齐真实意图口径

评估集 `evals/cases.jsonl` SHALL 以 `输入 → 期望意图` 为用例,且 `expected_intent` MUST 取自真实分类器的 5 类口径之一:`appointment`、`query`、`pay`、`statistics`、`other`。用例集 SHALL 覆盖全部 5 类,并包含边界场景(多槽位、缺槽位追问、改约、与服务无关的输入)。

用例集 SHALL 划分为 **dev** 与 **held-out** 两个子集(集归属规则见「用例集 dev / held-out 切分」需求)。**dev 子集**的总量 SHALL 不少于 40 条,且每一类意图在 dev 子集中 SHALL 不少于 5 条(使按类目分项指标具备最低统计意义);**held-out 子集**总量 SHALL 不少于 10 条并至少覆盖 3 类意图。全集(dev + held-out)总量 SHALL 不少于 18 条(向后兼容既有下限)。

用例的「输入」SHALL 支持两种形态,二者向后兼容:

- **单轮**:`input` 为单条用户话语字符串(既有形态,不变)。
- **多轮**:`turns` 为有序的用户话语字符串列表(每个元素是一轮用户输入)。一条用例 SHALL 提供 `input` 与 `turns` 之一;同时提供时 MUST 报错指出行号。单轮 `input` 在语义上等价于单元素 `turns`。

无论单轮还是多轮,`expected_intent` MUST 取自上述 5 类之一;多轮用例的 `expected_tools` / `expected_slots`(若标注)的口径为**整段对话累计**——即期望工具序列/期望槽位键集为跨所有轮次合并后的集合,与既有单轮口径在「单元素 turns」上自然一致。

#### Scenario: 用例意图取值合法

- **WHEN** 加载 `cases.jsonl` 中任一非注释用例
- **THEN** 其 `expected_intent` 必须是 `{appointment, query, pay, statistics, other}` 之一,否则运行器报错并指出行号

#### Scenario: 五类全覆盖

- **WHEN** 统计用例集的 `expected_intent` 分布
- **THEN** 5 个类目每个至少出现一次

#### Scenario: dev 子集规模与每类下限

- **WHEN** 统计 dev 子集的用例数与按类目分布
- **THEN** dev 子集总量不少于 40 条,且每一类意图在 dev 子集中不少于 5 条

#### Scenario: held-out 子集规模与覆盖

- **WHEN** 统计 held-out 子集的用例数与意图覆盖
- **THEN** held-out 子集总量不少于 10 条并至少覆盖 3 类意图

#### Scenario: 注释与空行被跳过

- **WHEN** 文件含 `//` 开头的注释行或空行
- **THEN** 运行器加载时跳过它们,不计入用例

#### Scenario: 多轮用例以 turns 列表表达

- **WHEN** 一条用例提供 `turns`(字符串列表)而非 `input`
- **THEN** 运行器 SHALL 加载该用例并按多轮路径评估,其 `expected_intent` 校验与单轮用例一致

#### Scenario: input 与 turns 互斥

- **WHEN** 一条用例同时提供了 `input` 与 `turns`(或两者皆缺)
- **THEN** 运行器 SHALL 报错并指出行号,MUST NOT 静默猜测

## ADDED Requirements

### Requirement: 用例集 dev / held-out 切分

评估集的每条用例 SHALL 携带一个「集归属」标记以区分 **dev** 与 **held-out**;未显式标记的用例 SHALL 默认归入 **dev**(向后兼容——既有用例无需改动即属 dev)。切分的目的是防过拟合:held-out 子集**用作过拟合体检的留出集**,MUST NOT 被用于任何 prompt / 用例 / 阈值的调优,也 MUST NOT 参与门禁基线的生成与回归判定。

运行器 `evals/run_evals.py` SHALL 满足:

- **默认只评 dev**:不带 held-out 开关时,运行器 SHALL 只加载并评估 dev 子集;意图准确率、工具/槽位指标、`--update-baseline`、`--gate` 的口径 SHALL 全部基于 dev 子集,与本变更前的默认行为等价(held-out 用例被排除,不影响任何既有数字与门禁)。
- **按需评 held-out**:提供显式开关(如 `--include-heldout` 或 `--heldout-only`)时,运行器 SHALL 评估 held-out 子集并**单独分集呈现**其指标,MUST NOT 把 held-out 结果混入 dev 基线或触发门禁的非零退出。
- **分集透明**:报告 SHALL 标明各指标是在 dev 还是 held-out 子集上计算、以及各子集用例数,MUST NOT 让读者误以为 held-out 参与了门禁。

集归属的校验 SHALL 与既有加载校验一致(非法标记值报行号退出),集归属标记 SHALL 进 git、可追溯。

#### Scenario: 默认运行只评 dev 且门禁基于 dev

- **WHEN** 不带 held-out 开关运行 `uv run python evals/run_evals.py`(或 `--gate` / `--update-baseline`)
- **THEN** 运行器只加载 dev 子集,所有指标、基线与门禁判定均基于 dev;held-out 用例被排除,不影响任何数字或退出码

#### Scenario: 显式请求时按需评 held-out 并分集呈现

- **WHEN** 带 held-out 开关运行运行器
- **THEN** held-out 子集被评估、其指标单独分集呈现,MUST NOT 混入 dev 基线,MUST NOT 触发门禁非零退出

#### Scenario: 未标记用例默认归 dev(向后兼容)

- **WHEN** 加载一条未携带集归属标记的既有用例
- **THEN** 该用例归入 dev 子集,评估行为与本变更前完全一致

#### Scenario: 非法集归属标记报错

- **WHEN** 一条用例的集归属标记不是 `{dev, held-out}` 之一
- **THEN** 运行器报错并指出行号,MUST NOT 静默归类

#### Scenario: held-out 不参与调优与门禁

- **WHEN** 生成门禁基线(`--update-baseline`)或执行回归判定(`--gate`)
- **THEN** 只有 dev 子集参与;held-out 子集 MUST NOT 影响基线内容或回归结论
