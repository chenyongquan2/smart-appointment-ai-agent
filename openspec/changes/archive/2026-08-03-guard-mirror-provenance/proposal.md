## Why

`locate_service_code` 读 `refs/heads/{branch}`（[services/repo.py:266](../../../services/repo.py) 校验、`:295`/`:327` checkout）。这个读法**对正规远端 clone 出来的 mirror 是对的**——GitLab 服务端的分支都在 `refs/heads/*` 下。

但 `git clone --mirror` 的 refspec 是 `+refs/*:refs/*`，它会把上游**整个 refs 命名空间**原样搬过来。若上游是一份**本地工作副本**，那么搬过来的 `refs/heads/*` 只反映"开发者本地那个分支拉到哪"，真实远端状态在 `refs/remotes/origin/*` 里。2026-08-03 实测的三种后果：

| 服务 | mirror 来源 | 现象 |
|---|---|---|
| `ocs5` | 工作副本 | `refs/heads/OCS5/prd` 落后 **279** 个 commit（uat 306、stg 325）——**静默返回旧代码，零提示** |
| `mttools` | 工作副本 | `refs/heads/MTTools/*` 根本不存在（只在 `refs/remotes/origin/` 下）→ 报 `branch_not_found`，**不说明真实原因** |
| `ocs4` | 工作副本 | 恰好同步——**不是正确，是运气好**；上游一落后它就跟着落后 |

**静默那个比报错危险得多**：同事问"这段逻辑在哪"，拿到约 300 个 commit 前的代码而毫无提示，会基于错的代码下判断。这是「沉默不是中立」在本项目的第四次出现（前三次在工具层 / 可观测层 / 护栏层）。

顺带解释了为什么"TTL 内 fetch 同步"没起作用：在这种 mirror 里 `fetch` 写的是 `refs/remotes/origin/*`，**同步的地方和代码读的地方不是同一个**。

已在 [docs/oncall-bot-roadmap.md](../../../docs/oncall-bot-roadmap.md) 第 3 期记为「建议的后续守卫（未做）」。当时的正解是"从正规远端重做 mirror"（零代码），但那**只修了当下这两个 mirror，没修下一次**——运维再从工作副本 clone 一次，同样的静默会原样重演。本变更把它变成机制。

## What Changes

- **新增来源探测**：mirror 里若存在任何 `refs/remotes/*` ref，即判定它来自工作副本（正规远端 clone 出的 mirror 没有这个命名空间）。
- **`ready` 结果附带落后量**：来源可疑时，比对 `refs/heads/{branch}` 与 `refs/remotes/origin/{branch}`，把落后的 commit 数**结构化带回**。落后 0 也照报来源可疑（今天对只是运气好）。
- **`branch_not_found` 说明真实原因**：分支在 `refs/heads/` 找不到、但在 `refs/remotes/origin/` 下存在时，明说"mirror 来自工作副本，该分支只存在于远端跟踪引用下"，而不是让用户以为仓库里没这个分支。
- **不自动绕行**：**MUST NOT** 在探测到可疑来源时改读 `refs/remotes/origin/*` 来"修好它"。那是把错误配置藏起来，本项目一贯的做法是暴露而非兜底；且绕行会让运维永远不知道 mirror 建错了。
- **不阻断**：来源可疑仍返回 `ready`（带警示）。落后 0 时阻断毫无收益，落后时把判断权交给值守的人比直接罢工有用。

非破坏性：`LocateResult` 只增字段，既有 `status` 取值与语义一律不变。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `oncall-domain`：`源码定位` 这条 Requirement 的行为扩展——新增"来源可疑与落后量必须如实带回、MUST NOT 静默返回旧代码"，并给 `branch_not_found` 补一条区分真实原因的 Scenario。

## Impact

- **代码**：[services/repo.py](../../../services/repo.py)（新增探测函数、`LocateResult` 增字段、`_ensure_worktree` / `locate_service_code` 接线）、[domains/oncall/tools/code.py](../../../domains/oncall/tools/code.py)（把警示渲染进工具返回文本，否则模型看不见）。
- **测试**：[tests/test_oncall_code.py](../../../tests/test_oncall_code.py) 新增夹具——用真实 git 造「origin(bare) → 工作副本 → mirror 工作副本」三级，复现落后与"分支只在 remotes 下"两种实况。
- **文档**：roadmap 第 3 期把「建议的后续守卫（未做）」改为已做。
- **不影响**：日志查询、MT 文档检索、权限策略、harness 运行时一行不动。正规远端建的 mirror 行为完全不变（探测结果为否，不加任何字段）。
