## Context

[services/repo.py](../../../services/repo.py) 用 `refs/heads/{branch}` 三处：`_resolve_env_branch:266` 校验存在、`_ensure_worktree:295` 建 worktree、`_sync:327` checkout。这个读法对**正规远端 clone 的 mirror 是正确的**——服务端 refs 命名空间只有 `refs/heads/*` 与 `refs/tags/*`。

问题出在 mirror 的**来源**上，不在读法上。`--mirror` 的 refspec 是 `+refs/*:refs/*`，从工作副本 clone 会把上游的 `refs/remotes/origin/*` 一并搬来；此时 `refs/heads/*` 是"上游开发者本地拉到哪"，`refs/remotes/origin/*` 才是它上次 fetch 到的真实远端状态。

2026-08-03 实测三例（详见 proposal）：`ocs5` 静默落后 279 个 commit、`mttools` 报 `branch_not_found` 不说原因、`ocs4` 恰好同步纯属运气。

当时的处置是「从正规远端重做 mirror」——零代码，但**只修了这两个 mirror，没修下一次**。本变更把一次性修复变成常驻机制。

约束：值守域全工具只读（[domains/oncall/policy.py](../../../domains/oncall/policy.py) 硬 enforce），本变更不得引入任何写操作；git 子进程须沿用既有的「下沉线程池 + 子进程自带超时」两件套。

## Goals / Non-Goals

**Goals:**

- 探测 mirror 来源，来源可疑时在定位结果中明确标出。
- 给出**落后的 commit 数**这个具体数字，而不是一句模糊的"可能过期"。
- `branch_not_found` 能区分「仓库里真没这个分支」与「分支只在远端跟踪引用下」。
- 警示必须抵达模型可见的文本，不能只躺在结构化字段里。

**Non-Goals:**

- 不自动绕行到 `refs/remotes/*`（见 D3）。
- 不阻断定位（见 D4）。
- 不改 `_sync` 的 fetch 行为、不改分支候选解析逻辑、不动 `code_search` / `read_source` 的 jail 三层。
- 不做"帮你重建 mirror"——那是写操作，值守域红线之外。

## Decisions

### D1 判据用「refs 命名空间里有没有 `refs/remotes/`」，不用 git config

**选它**：`git -C <mirror> for-each-ref --count=1 refs/remotes/`，有输出即判定来源为工作副本。

**为什么不看 config**：直觉上会想查 `remote.origin.mirror` 或 `remote.origin.url`。两条都不成立——

- `remote.origin.mirror=true` 在**两种** mirror 里都是 true（都是 `--mirror` 建的），区分不了；
- `remote.origin.url` 指向工作副本路径这一点确实能看出来，但它是**可改的**（运维事后 `set-url` 到正规远端就骗过了检查），而 refs 命名空间是**已经搬进来的既成事实**，改 url 不会让 `refs/remotes/*` 消失。

判据要选"被污染的证据"而不是"声明的意图"。

### D2 落后量用 commit 数，不用布尔

`git -C <mirror> rev-list --count refs/heads/{b}..refs/remotes/origin/{b}`。

**为什么要数字**：`ocs5` 那次的说服力全在"279"这个数上。一句"该分支可能不是最新"读起来像免责声明，容易被无视；"落后 279 个 commit"没法无视。这与本项目在日志查询上的既有做法一致（总数与样本数分别呈现，不含糊）。

**方向只算落后不算领先**：`A..B` 只数 B 独有的提交。工作副本可能有未推送的本地提交（`refs/heads` 反而领先），那不构成"拿到旧代码"的风险，不报。

**远端跟踪引用可能不存在**（本地建的分支从没推过）：此时落后量为 `None`，只报来源可疑，不编数字。

### D3 MUST NOT 自动改读 `refs/remotes/*`

技术上完全可行：探测到可疑就把 checkout 目标换成 `refs/remotes/origin/{b}`，用户立刻拿到正确代码。**不这么做**，两个理由：

1. 它把错误配置**藏起来**——运维永远不知道 mirror 建错了，下一个仓库继续错，而且错得更隐蔽（因为"看起来能用"）。
2. 它让 `_sync` 的语义变成分叉的两套（正规 mirror 读 heads、可疑 mirror 读 remotes），后续任何人改这块都要同时想两条路径。

本项目一贯是暴露而非兜底。正解是运维重做 mirror，而本变更的职责是**让人知道该重做了**。

### D4 不阻断，返回 `ready` + 警示

**替代方案**：新增一个 `mirror_from_worktree` 引导状态，直接拒绝定位。

**不选它**：落后 0 时（`ocs4` 那种）阻断纯属误伤，而落后时值守的人完全可能判断"这段代码几年没动过，299 个 commit 不影响我要看的那个函数"。把判断权交给人比替他罢工有用。代价是**依赖警示真的被看见**——所以有 D5。

### D5 警示要进模型可见文本，且三个工具都带

`locate_service_code` 的 handler 返回 `result.to_dict()`，加字段即到模型眼前。但 `code_search` / `read_source` 走的是 `_require_worktree`（[domains/oncall/tools/code.py:35](../../../domains/oncall/tools/code.py)），它只取 `Path`、丢掉整个 `LocateResult`——**模型完全可以不调 locate 直接 search**，那条路径上警示会整个消失。

故 `_require_worktree` 改为把警示一并带出，三个工具的返回里都挂上。除结构化字段外另给一句人话 `mirror_warning`，因为模型对"字段名 + 数字"的重视程度不如一句明确的话。

这一点是本变更最容易做漏的地方：只改 `locate` 会得到一个"看起来做了、实际半数路径仍然静默"的守卫——恰恰是本变更要消灭的那类缺陷。

### D6 来源探测按 `repo_dir` 缓存，落后量不缓存

来源在进程生命周期内不会变（除非有人重做 mirror 并重启），一次 `for-each-ref` 缓存住即可。落后量会随 `_sync` 的 fetch 变化，每次实算——它只是一条 `rev-list --count`，与既有的 `rev-parse` / `fetch` 同量级。

### D7 `branch_not_found` 的原因区分只在来源可疑时查

分支在 `refs/heads/` 找不到时，若来源可疑，再查一次 `refs/remotes/origin/{cand}`。正规 mirror 上跳过这步——那里 `refs/remotes/` 本来就是空的，查了必然没有，白费一个子进程。

## Risks / Trade-offs

- **误报：有人在正规 mirror 里手工 `git remote add` 过** → 缓解：警示措辞用"疑似来自工作副本"并**明写判据**（"该 mirror 下存在 refs/remotes/ 引用"），让人能自己核实而不是盲信；不阻断（D4）也让误报的代价止于一句多余的提示。
- **落后量为 0 时仍报警示，可能被当成噪声** → 缓解：文案分档——落后 >0 是"⚠ 可能拿到旧代码"，落后 0 是"来源不规范，当前恰好同步"。两者语气不同，避免狼来了。
- **多报一层信息会挤占模型上下文** → 缓解：正规 mirror 上一个字段都不加（探测为否即完全不出现），只有真出问题的仓库才有额外文本。
- **`for-each-ref` / `rev-list` 在超大仓库上的耗时** → 两条都是 refs 层操作、不遍历对象库，与既有 `rev-parse --verify` 同量级；且沿用既有 `_git` 的线程池 + 超时，最坏情况是超时后按"探测不出"处理（**降级方向要选保守**：探测失败时不报警示，避免把 git 抽风渲染成"你的 mirror 有问题"）。

## Migration Plan

无数据迁移。`LocateResult` 只增可选字段，`to_dict()` 在字段为 `None` 时不输出，既有调用方与既有测试不受影响。

回滚 = 撤掉该 change 的提交；没有持久化状态、没有配置项、没有 schema 变更。

## Open Questions

- 探测到可疑来源时是否该同时写一条结构化日志（供后续 trace triage 统计"有多少次排障是在可疑 mirror 上做的"）？倾向做，但归入本变更会拖进可观测层，**留作后续**——先让人看见，再谈统计。
