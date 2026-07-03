## Context

评测机制已齐全(端到端多轮 + 门禁 + 在线闭环),但数据集是短板:35 条、合成、无 dev/held-out 切分,导致指标统计意义弱、且有在同一批数据上调优的过拟合风险(教材 §4.2)。本切片解决「机制」——把切分立起来 + 做首个有意义的规模化增量,不追求几百条完整规模化(那是"持续投入")。

约束(沿用改造 8 禁改清单):纯数据集 + `evals/` 层变更,**不改** `services/` / `harness/runtime` / 子 Agent 提示。改 `cases.jsonl` 必连带重定 `baseline.json`(见记忆 eval-trigger-nondeterminism)。

## Goals / Non-Goals

**Goals:**
- 用例增加「集归属(dev / held-out)」维度,运行器默认只评 dev,held-out 仅按需评、绝不参与调优与门禁。
- dev 子集扩到「每类 ≥5、总 ≥40」;新增 held-out 子集「≥10 条、≥3 类」。
- 默认行为、门禁口径**对现状完全向后兼容**(未标记 = dev;不带开关跑 = 只评 dev)。
- 在新 dev 集上重定 baseline(人审)。

**Non-Goals:**
- 从真实流量采样(依赖改造 7 有真流量)。
- 完整规模化到几百条(仍是持续投入,后续切片)。
- 自动生成用例的流水线;任何 judge/门禁阈值调整。

## Decisions

### D1. 集归属用**行内 `split` 字段**,而非独立文件
每条用例 JSON 增加可选 `"split": "dev" | "held-out"`,**缺省即 dev**。
- **为什么**:① 向后兼容——既有 35 条不动一字即属 dev;② 单一 source of truth、一处版本化,`load_cases` 已逐行解析,改动最小;③ dev/held-out 分布可在同文件一眼看全,便于校验「每类 ≥5」。
- **备选**:独立 `cases_heldout.jsonl`。物理隔离对「held-out 不泄漏进调优」保证更强,但引入第二份加载路径、双份注释/校验、分布难合并统计。
- **权衡**:字段方案的「不泄漏」保证靠**运行器默认只评 dev + 纪律**(见 D2),非物理隔离;考虑到本项目单人开发、held-out 语义已写入 spec,纪律足够,不值得双文件的复杂度。

### D2. 运行器:加载期打标 + 默认 dev 过滤 + 分集报告
- `load_cases` 识别 `split`(非 `{dev, held-out}` → 报行号 `SystemExit(2)`,与既有标签校验一致),给每条 `EvalCase` 附 `split`。
- 新增开关:`--include-heldout`(dev + held-out 都评、分集呈现)与 `--heldout-only`(只评 held-out)。**不带开关 = 只评 dev**,`--update-baseline` / `--gate` 恒基于 dev(held-out 被过滤,MUST NOT 影响基线内容或退出码)。
- 报告分集:标明每个指标算在 dev 还是 held-out、各子集用例数;held-out 结果单独一节,明确「不参与门禁」。

### D3. 规模化增量策略:**新增补足,不迁移既有**
- 既有 35 条**保持 dev**,在此之上新增合成用例补足「每类 ≥5、dev 总 ≥40」的缺口(按当前类目分布查漏)。
- held-out **另写新用例**(≥10、≥3 类),而非从 dev 抽走——避免 dev 缩水、也让 held-out 是"没在 dev 里出现过"的新分布样本(更贴合留出集本义)。
- 保持单轮/多轮两形态、`appointment` 用例含「预约」二字(防误判 other)、信息齐全预约用例沿用改造 8 的祈使式锚点风格以维持工具触发概率。

### D4. 基线:仅 dev、人审重定
新增用例改变了 dev 集 → 旧基线 apples-to-oranges。在新 dev 集 `--update-baseline --samples 3` 重定,记录刷新后意图/工具F1/槽位均值;held-out 不进基线。走人审、不自动(不绕过改造 6 门禁)。

## Risks / Trade-offs

- **[held-out 泄漏进调优]** → 字段方案无物理隔离;缓解:spec 明文禁止 + 运行器默认排除 held-out + 报告显式标注「held-out 不参与门禁」,让误用需要显式开关、不会无意发生。
- **[合成用例仍不代表真实分布]** → 本切片仍是手写合成,统计意义提升但分布偏差未解;缓解:诚实写入 README/教材,真实分布靠改造 7 在线回灌(后续)。
- **[新增用例加大门禁抖动]** → 工具触发强非确定,新预约锚点可能拉低/抖动工具 F1;缓解:沿用「数据集冗余 + `--samples 3` + 容差」,重定基线如实反映新集难度(不 relabel 粉饰)。
- **[held-out 太小,体检信号弱]** → ≥10 条的 held-out 指标 CI 很宽,只能做粗过拟合体检;缓解:定位为"体检"而非"结论",诚实标注;规模化留后续切片。

## Migration Plan

1. 加 `split` 支持 + 开关 + 分集报告(evals 层),补单测(离线确定性:dev 过滤、held-out 按需、未标记默认 dev、非法值报错)。
2. 扩充 dev 用例补足每类下限 + 新写 held-out 用例;`--limit` 冒烟 + 真 provider 抽样确认加载校验(dev/held-out 计数、5 类覆盖)。
3. `uv run pytest` 全绿(闸门 2)。
4. 人审批准后 `--update-baseline --samples 3` 重定;多次 `--gate` 确认稳定守 3 项(dev)。
5. 文档同步 → 归档。

回滚:纯增量,`git revert` 数据 + 运行器改动、恢复旧 `baseline.json` 即可。

## Open Questions

- dev 每类下限取 5、held-out 取 ≥10/≥3 类是否够——本切片按"最低统计意义"设,后续规模化再抬。
- 开关命名 `--include-heldout` / `--heldout-only` 是否够清晰(实现期可微调,不影响 spec 行为)。
