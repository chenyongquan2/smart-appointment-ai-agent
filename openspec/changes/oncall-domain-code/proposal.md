## Why

OnCall 路线第 3 期切片 2。切片 1 让值守 bot 能查日志了，但日志经常只能定位到"哪个服务、哪行报错"——**要回答"为什么这样"就得看源码**。参考系统的 `code-analysis` 正是干这个：定位服务源码 → 结合日志把根因讲清楚。

## 一个必须先说清的前提：直接移植 `repokit.py` 是不够的

参考系统里这条链是这样的：`repokit.py locate` 给出 worktree 路径 → **agent 用自己的 shell / 文件系统工具去 grep 和读**（或派 `explore` 子 agent 做检索）。

**我们的 harness 没有给模型任何文件系统工具。** 只移植 repokit，会得到一个"返回了路径、但模型读不了那个路径"的死工具。

所以本切片的实际范围不是"移植 669 行"，而是**把代码分析这件事在本项目的形态下重新实现**：git 定位层照搬 repokit 的确定性逻辑，再补两个**受管束的只读检索工具**，让模型真的能读到源码。

## What Changes

- **新增 `services/repo.py`**：移植 `repokit.py` 的确定性部分——镜像 ref 解析、service→仓库映射（registry）、env→分支候选解析（`-b` 优先、裸名兜底）、**per-env 常驻 detached worktree**、TTL 内跳过的 fetch 同步、`repo_dir` 合法性校验。**全部 git 子进程调用下沉线程池**（见 design D1）。
- **新增两个只读检索工具**：
  - `code_search`：在已定位的 worktree 内按模式检索，返回 `文件:行号 + 命中片段`（带上下文行）。
  - `read_source`：读指定文件的指定行段。
  两者都 **硬 jail 在 worktree 内**（路径规范化后必须仍在 worktree 子树中，否则拒绝），`dangerous=False`。
- **新增 `locate_service_code` 工具**：service + env → worktree 是否就绪、HEAD sha、分支；未就绪时返回 `need_clone` / `branch_not_found` 等**引导状态**而非报错。
- **不提供 clone 工具**（见下）。仓库由运维预先 clone 进 `repos/`，`locate` 落空时自动发现并注册。

## 三条红线级的判断

**1. 不做 `clone`，因为它会被值守域的只读策略直接拒掉。**

`git clone` 是写操作（落盘 + 网络拉取），标 `dangerous=True` 就会被 `domains/oncall/policy.py` 拒绝——这正是那条策略该做的事。参考系统靠"clone 前硬确认 + 埋锚点"这套人工闸门来兜，本项目的答案更简单：**agent 根本不 clone**。仓库不在本地时返回 `need_clone`，让模型告诉用户"请运维先把仓库放进来"。红线不打折，也省掉一整套确认机制。

**2. `fetch` 同步保留，但它是"读远端 + 本地缓存"，不是写操作。**

`git fetch` 不改远端、不改历史、不产生提交，只更新本地镜像的 refs。归类为只读，但**必须有 TTL**（缺省 60 秒内跳过），否则每次分析都拉一次网络。

**3. 检索工具必须硬 jail。**

`read_source` 若接受任意路径，就是一个任意文件读取工具——能读到 `.env`、SSH key、本仓源码。参考系统吃过这个亏：2026-06-10 有过"绕道注册绝对路径 → 读码全被拒 → 300 秒超时"的事故，它的对策是在 repokit 层拒绝 `repos/` 外的路径。本项目照做，且在**工具层再 jail 一次**——路径经 `resolve()` 后必须仍在目标 worktree 子树内。

## Capabilities

### New Capabilities
- 无。扩充既有的 `oncall-domain` 能力。

### Modified Capabilities
- `oncall-domain`: 新增三组需求——**源码定位**（service+env→worktree，未就绪时给引导状态而非报错；**MUST NOT 提供 clone 能力**）、**受管束的只读检索**（硬 jail、返回文件:行号+片段、行数上限但不截断单行）、**同步阻塞调用下沉线程池**（git 子进程用 `subprocess`，`asyncio.wait_for` 掐不断它——这是 `Tool.timeout` 的已知适用边界，第 1 期评审时就写明了「第 3 期移植 repokit 的 git 子进程时会误以为有保护」）。

## Impact

**新增**：`services/repo.py`、`domains/oncall/tools/code.py`（三个工具）、`repos/` 目录约定（gitignore）。

**改动**：`domains/oncall/tools/__init__.py`（注册三个工具）、`domains/oncall/prompt.py`（补代码分析的行为策略：只读红线、结论分级、不可见环节如实标注）、`.env.example`（`ONCALL_REPOS_DIR`）、`.gitignore`。

**不改**：`harness/`、`executor/`、`channels/`、预约域、`evals/`。

**测试**：全部离线，用**临时 git 仓库**（`git init` + 造几个提交/分支）驱动真实 git 命令——不 mock git，因为要验的正是分支候选解析、worktree 创建这些 git 行为。含：jail 越界被拒（`../`、绝对路径、符号链接）、TTL 跳过、`need_clone` 引导状态、**心跳不停**（git 子进程挂起时事件循环仍推进）。

⚠ **验收边界**：真实公司仓库（内网 git、私有镜像）无法在 CI 验证。离线测试证明的是"git 逻辑正确、jail 拦得住、异步不阻塞"；**"能不能定位到真实服务的源码"需人工冒烟**，与切片 1 的 `VM_LOGS_*` 冒烟同属挂起项。
