## MODIFIED Requirements

### Requirement: 从持久化 trace 半自动甄别坏 case

系统 SHALL 提供一个 triage 流程，从落盘的 trace 文件读入运行记录，依据**已有客观信号**给每条 trace 标注「疑似坏」候选状态。可用信号 MUST 至少包含：护栏耗尽、打转、循环达到 `max_steps` 而未产出终态回复、span 中出现工具调用异常、**工具超时**（loop 级中断与 service 级结构化 `error_kind` 两条路径均须覆盖）、**同一工具换参重复调用**（同一 (工具, 身份参数) 组合跨 ≥N 个步骤出现，见 `observability`）。甄别 MUST 为纯函数式判定（给定一组 span / trace 记录即可离线确定地得出候选清单），MUST NOT 触网、MUST NOT 调用 LLM。甄别只产出「候选」，MUST NOT 自行判定真值或自动改写评估集。

读入 trace 记录时，排序与时间筛选 SHALL 优先使用 span 的墙钟起始时刻；该字段缺失时 MUST 回退到文件行序（同一 tracer 按完成顺序追加，与按 start 排序一致）。**已落盘的历史 trace 文件 MUST 仍可被正常加载**——引入墙钟字段 MUST NOT 使既有真实流量记录失效。

新增信号 MUST NOT 降低候选清单的信噪比：真实数据中存在的正当模式（逐维度枚举、换检索策略、多意图并行检索）MUST NOT 因该信号进入候选。

> 口径修正（change `fix-trace-triage-blindspots`）：原信号集列有「最终回复带 `[ERROR]` 前缀」。该前缀是遗留 `agents/` 路径的产物，当前生产走的 harness `AgentLoop` 只产 `[THOUGHT]`/`[REPLY]`，故该信号永不命中——原文属规格要求了一个实现刻意不做的信号。此处按真实落点重述。

#### Scenario: 命中失控信号的 trace 被标为候选

- **WHEN** 对一批含「达到 max_steps」「工具异常」「工具超时」「同工具换参重复」的 trace 跑甄别
- **THEN** 这些 trace 被列入「疑似坏」候选清单，未命中任何信号的 trace 不在候选中

#### Scenario: 甄别可离线确定性测试

- **WHEN** 在内存中构造若干带/不带失控信号的 span 记录并跑甄别
- **THEN** 候选判定结果确定可复现，全程不发起网络调用、不调用 LLM

#### Scenario: 历史 trace 文件仍可加载

- **WHEN** 对不含墙钟字段的既有 trace 文件跑甄别
- **THEN** 该文件被正常解析，span 顺序回退按文件行序确定，甄别结果与引入墙钟字段前一致

#### Scenario: 正当检索模式不进候选

- **WHEN** 对含「逐维度枚举」「换检索策略」「多意图并行检索」的 trace 跑甄别
- **THEN** 这些 trace MUST NOT 因「同工具换参重复」信号进入候选清单
