## Context

切片 1 让值守 bot 能查日志。但日志给出的常是"哪个服务、哪行报错"，要回答"为什么会这样"必须看源码。参考系统的 `code-analysis` 这条链是：`repokit.py locate` → worktree 路径 → **agent 自己 grep/读**（或派 `explore` 子 agent 检索）。

那条链在本项目断在最后一步：**我们的 harness 不给模型文件系统工具**。所以本切片不是"移植 669 行"，而是把这件事在本项目的形态下重新搭一遍——git 定位层照搬 `repokit` 的确定性逻辑，检索层新写两个受管束的工具。

`repokit.py` 里有大量 CLI 与交互引导逻辑（registry CRUD 子命令、clone 确认流程、parse-image 建议值），本切片只取其中**确定性、且本项目用得上**的部分。

## Goals / Non-Goals

**Goals:**
- service + env → 已同步的 worktree 路径，未就绪时给**可操作的引导状态**而非报错。
- 模型能在那个 worktree 内**只读**检索与阅读源码，且越不出去。
- git 子进程不冻住事件循环。
- 只读红线不打折：不提供任何写操作能力。

**Non-Goals:**
- **不做 clone**（见 D2）。
- 不做 registry 的增删改工具——映射表由运维维护文件，agent 只读。给 agent 一个"注册仓库地址"的工具等于让它改配置。
- 不做 `parse-image`：它的产出是"建议的 git 地址"，只在 clone 流程里有用；不 clone 就不需要。
- 不做代码修改、补丁、diff、PR 建议——这是值守域的最高红线。
- 不做跨仓库全局检索：检索范围恒为**一个已定位的 worktree**。

## Decisions

### D1 git 子进程下沉 `asyncio.to_thread`，且这次是**正确用法**

`subprocess.run` 是同步阻塞的。第 1 期设计评审时就写明过这个坑：「`asyncio.wait_for` 中断不了同步阻塞调用，同步工具须自行下沉线程池——否则第 3 期移植 `repokit.py` 的 git 子进程时会误以为有保护」。

值得说清的是，这与 `fix-embedding-timeout-blocking` 的 design D2 **否决** `asyncio.to_thread` 并不矛盾，两处的约束不同：

| | embedding 那次 | 本次 git 子进程 |
|---|---|---|
| 有没有原生异步替代 | **有**（`aembed_query`，走 httpx 异步栈） | **没有**（git 是外部进程，`asyncio.create_subprocess_exec` 是另一回事——见下） |
| `to_thread` 的缺陷 | 线程里的调用取消不掉、连接泄漏 | 同样取消不掉，但 **`subprocess` 自带 `timeout=`**，进程会被真正杀掉 |
| 故结论 | 用原生异步，不用线程池 | 用线程池 + **子进程自身的 timeout** |

关键在第三行：`subprocess.run(timeout=N)` 到点会 kill 掉子进程，所以"取消不掉"的窗口被子进程自己的超时封顶了，不会像 HTTP 连接那样无限期泄漏。**线程池 + 子进程超时两者缺一不可**——只有线程池会挂死到进程自然结束，只有超时会冻住事件循环。

（考虑过 `asyncio.create_subprocess_exec` 这个"真异步"方案。否决理由：Windows 上它需要 `ProactorEventLoop`，而本项目在 Windows 开发、Linux 部署，跨平台行为差异会引入一类只在某个平台复现的缺陷；而 `to_thread + timeout` 的行为在两个平台一致。这是取舍，不是遗漏。）

### D2 不提供 clone —— 让只读策略自己说话

`git clone` 会落盘、会拉网络，是写操作。若做成工具必须标 `dangerous=True`，而 `domains/oncall/policy.py` 会**直接拒绝**它。

参考系统的做法是靠"clone 前硬确认 + 埋锚点 + 结束本轮"这套人工闸门。本项目不需要那套：**agent 根本不 clone**。仓库不在本地时 `locate_service_code` 返回 `need_clone` 状态，模型据此告诉用户"这个服务的仓库还没准备好，请运维先 clone 到 repos/ 下"。

这样红线不打折（策略里没有例外条款），也省掉一整套确认机制。代价是首次分析某服务需要运维介入一次——在值守场景里可以接受，而且比"让 bot 自己往磁盘上拉代码"安全得多。

`git fetch` 则保留：它不改远端、不改历史、不产生提交，只更新本地镜像 refs，归类为"读远端 + 本地缓存"。但**必须有 TTL**（缺省 60 秒内跳过），否则每次分析都拉一次网络。

### D3 检索工具硬 jail，且**在两层都 jail**

`read_source` 若接受任意路径，就是一个任意文件读取工具——能读到 `.env`（里面有 `VM_LOGS_PASSWORD`、`FEISHU_APP_SECRET`）、SSH key、本仓源码。这是本切片最大的安全面。

三重约束：

1. **service 参数决定 worktree**：模型给的是 `service` + `env` + **相对路径**，不是绝对路径。绝对路径无从谈起。
2. **规范化后必须仍在子树内**：`(worktree / rel).resolve()` 必须 `is_relative_to(worktree.resolve())`。这挡住 `../../../etc/passwd`，也挡住**指向外部的符号链接**（`resolve()` 会跟随 symlink，所以检查发生在跟随之后）。
3. **`repo_dir` 只接受 `repos/` 下的纯目录名**（照搬 repokit 的 `_valid_repo_dir`）：拒绝绝对路径、路径分隔符、`..`。worktree 绝不落到 `repos/` 外。

参考系统在这上面吃过亏（2026-06-10：绕道注册绝对路径 → 读码全被拒 → 300 秒超时），它的对策是在 repokit 层拒绝仓库外路径。本项目照做，并在工具层再拦一次——**两层都拦**，因为这两层未来可能被独立修改。

### D4 检索返回"文件:行号 + 片段"，不返回整文件

`code_search` 返回命中行及其上下文（缺省前后各 3 行），带文件路径与行号；`read_source` 要求给行段（`start_line` + `line_count`，上限 200 行）。

**为什么不给"读整个文件"**：源码文件动辄几千行，一次读进上下文既贵又淹没关键信息。参考系统的 `explore` 子 agent 被明确要求"回精简结论、不回整文件"，是同一个道理。

与切片 1 的 `_msg` 那条**看似相反、实则同源**：那边是"截条数可以、截正文不行"，因为一条日志的根因常在正文靠后；这边是"限行数"，因为源码的行是天然的独立单位、截断不丢语义。判据都是**截断会不会破坏那个单位的完整性**。

### D5 分支候选解析照搬，包括"`-b` 优先、裸名兜底"

`ENV_BRANCH_CANDIDATES` 的形状（`prd → ["prd-b", "prd"]` 之类）是参考系统对公司分支命名实况的沉淀，照搬；解析时按候选顺序取第一个存在的分支，全都不存在则返回 `branch_not_found` **并带上已试候选列表**——那个列表是给用户看的（"我试了这几个分支名都没有，是不是叫别的"）。

env 口径有个坑要照搬：**vlog 用 `prod`，git 分支用 `prd`**。切片 1 的 `services/vlog.py` 里 `prd` 是 `prod` 的别名；这里反过来。service 层做一次归一，不让模型记两套。

### D6 worktree 是 detached、per-env 常驻，不加自定义锁

照搬参考系统的判断：每 service 每 env 固定一个常驻 detached worktree，并发 fetch 靠 git 自身的 refs `.lock`，多个 worktree detached 到同一 commit 互不冲突。`_git_lockretry` 那段"遇到 index.lock 之类就退避重试"的逻辑一并移植——它是真实并发下踩出来的。

**detached 而非 checkout 分支**：分析用的 worktree 不该有"当前分支"的概念，避免任何形式的意外写入影响分支状态。

## Risks / Trade-offs

- **[引入了文件读取能力，安全面变大]** → 这是本切片最需要 review 的地方。缓解：三重 jail（D3）、两层独立检查、无绝对路径入口、专门的越界测试（`../`、绝对路径、symlink 三类）。
- **[首次分析某服务需运维先 clone]** → D2 的自觉代价。缓解：`need_clone` 状态带上 service 名与建议，模型能给出明确的运维指引，而不是含糊的"失败了"。
- **[真实仓库无法在 CI 验证]** → 缓解：用 `git init` 造临时仓库跑真实 git 命令（不 mock git，要验的正是 git 行为）；真实公司仓库的定位标记为人工冒烟项，与切片 1 的 `VM_LOGS_*` 同属挂起。
- **[git 子进程仍可能拖慢单次工具调用]** → 缓解：子进程自带 timeout；`Tool.timeout` 作为第二层（虽然它掐不断同步调用，但线程池 + 子进程超时已经封顶）。

## Migration Plan

1. `services/repo.py` + 临时 git 仓库驱动的离线测试（纯 service，无工具）。
2. 三个工具接上，jail 测试先行。
3. prompt 补代码分析的行为策略。
4. 冒烟：`AGENT_DOMAIN=oncall` 下 registry 里有五个工具。

**回滚**：单分支 revert；不注册 oncall 域即完全不影响预约域。

## Open Questions

- `repos/` 放仓库根还是可配目录——实现时定，倾向可配（`ONCALL_REPOS_DIR`，缺省仓库根下的 `repos/`），因为部署环境可能要把它放到大盘符上。
- 切片 3 的文档检索与本切片的 `code_search` 是否该合并成一个"检索"工具——不合并，检索对象与语义都不同（源码 vs 文档库），合并只会让 description 变糊。
