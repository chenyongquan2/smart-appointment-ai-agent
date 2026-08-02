> **移植纪律**：只取 `repokit.py` 里**确定性、且本项目用得上**的部分。CLI 引导流程、
> registry CRUD 子命令、clone 确认机制**一概不移植**——本项目不 clone（见 design D2），
> 映射表由运维维护文件、agent 只读。
>
> **最需要 review 的是 jail**：`read_source` 一旦能读任意路径，就是把 `.env` 里的
> `VM_LOGS_PASSWORD` / `FEISHU_APP_SECRET` 暴露给模型。三重约束缺一不可。

## 1. services/repo.py（纯 service，用临时 git 仓库驱动测试）

- [x] 1.1 `config/` 新增 `ONCALL_REPOS_DIR`（缺省仓库根下 `repos/`）与 git 子进程超时 `ONCALL_GIT_TIMEOUT_SECONDS`（缺省 120）。同步 `.env.example` 与 `.gitignore`（`repos/` 不进版本库）。
- [x] 1.2 `_run_git`：`asyncio.to_thread` + `subprocess.run(timeout=...)`。**两者缺一不可**——只下沉会挂到子进程自然结束，只超时会冻住事件循环（design D1）。注释里写明这与 `fix-embedding-timeout-blocking` 否决 `to_thread` 不矛盾的理由（那边有原生异步替代、且连接会泄漏；这边没有替代、且子进程超时封了顶）。
- [x] 1.3 `_valid_repo_dir` 照搬：只接受 `repos/` 下**纯目录名**，拒绝绝对路径 / 路径分隔符 / `..`。这是 jail 的第一层。
- [x] 1.4 registry 读取（**只读**，不做增删改）：`repos/registry.json` 的 service→`{repo_dir, git_url}` 映射；落空时自动发现 `repos/<service>/` 下运维手工 clone 的仓库（读其 origin URL）。**自动发现只看 `repos/` 内**，绝不向仓库外找。
- [x] 1.5 env→分支候选解析照搬（带环境后缀优先、裸名兜底），全不存在时返回 `branch_not_found` **并带回已试候选列表**（那是给用户判断"是不是分支叫别的"的唯一依据）。
- [x] 1.6 **env 口径归一**：vlog 用 `prod`、git 分支用 `prd`，两边相反。service 层做一次归一，别让模型记两套。
- [x] 1.7 `ensure_worktree`：per-service-per-env 常驻 **detached** worktree；`_git_lockretry`（遇 `index.lock` 之类退避重试）一并移植——那是真实并发踩出来的。
- [x] 1.8 `sync`：`fetch` 到 mirror + 快进 worktree，**TTL 内跳过**（缺省 60s）。fetch 归类为「读远端 + 本地缓存」故保留；**不做 clone**（design D2）。
- [x] 1.9 离线测试用**真实 git**（`git init` 造临时仓库 + 造分支/提交），不 mock git——要验的正是分支候选解析、worktree 创建这些 git 行为。含：候选顺序、`branch_not_found` 带候选、TTL 跳过、`need_clone`、非法 `repo_dir` 被拒。
- [x] 1.10 **「心跳不停」测试**：git 子进程挂起期间事件循环仍推进（造一个慢命令或用 fake），带 `@pytest.mark.timeout`。

## 2. 三个工具（jail 先行）

- [x] 2.1 `locate_service_code`：service + env → `ready` / `need_clone` / `branch_not_found` / `bad_env` 等状态 + worktree 路径 + HEAD + 分支。`dangerous=False`。
- [x] 2.2 `code_search`：在已定位 worktree 内检索，返回 `文件相对路径:行号 + 片段`（缺省前后各 3 行上下文）。结果条数有上限。
- [x] 2.3 `read_source`：读指定文件的指定行段（`start_line` + `line_count`，上限 200 行）。**不提供"读整个文件"**——源码动辄数千行，整读既贵又淹没重点。
- [x] 2.4 ★ **jail 第二层**（工具层，与 service 层独立）：入参只接受**相对路径**；`(worktree / rel).resolve()` 必须 `is_relative_to(worktree.resolve())`。**检查发生在 resolve 之后**，故也挡得住指向外部的符号链接。
- [x] 2.5 ★ **越界测试三类**已写：`../` 逃逸、绝对路径、指向外部的符号链接。前两类在本机通过；**symlink 那条在 Windows 上 skip**（创建符号链接需开发者模式），skip 理由已写在 `pytest.skip()` 里、不是静默略过。⚠ **该条在 Linux CI 上才真正被验证**——本机的绿不代表 symlink 拦得住。
- [x] 2.6 三个工具进 `TOOLS`；域装载后 registry 里共五个工具、全部 `dangerous=False`。

## 3. prompt 补代码分析的行为策略

- [x] 3.1 **最高红线**：只读分析——只定位、只解释、只回答；**绝不改代码、不写补丁、不出 diff、不提 PR，连"下一步建议"里都不列改码动作**。把根因 + 精确位置（文件/类/方法/行号）讲清即交付完毕，怎么修由用户定。
- [x] 3.2 **先枚举、再用证据排除**：给某错误码定位抛出点时，先全局检索**所有**抛出位置（通常不止一处），列出各自触发条件，再用**日志证据**逐一排除。绝不只取"离嫌疑调用最近的那处"就开始论证；枚举完仍凭直觉押注 = 白枚举。
- [x] 3.3 **结论分级**：纯代码推演（未与日志核对）的根因一律标"推测"；多个候选都未被排除时**并列陈述 + 各给验证方法**，不替用户押注。
- [x] 3.4 **推理链上有不可见环节时**：绝不假装看到了——写明哪一环不可见、推断依据是什么，标"推测"，请用户确认；确认前基于该推断的下游结论不得当事实交付。
- [x] 3.5 **仓库未就绪**：如实说"该服务仓库还没准备好，请运维先 clone 到 repos/ 下"，**绝不在本机别处找 checkout**（参考系统 2026-06-10 事故：绕道注册绝对路径 → 读码全被拒 → 300s 超时）。

## 4. 验证与收尾

- [x] 4.1 `uv run pytest` 全绿，通过数差额说清。
- [x] 4.2 冒烟：`AGENT_DOMAIN=oncall` 起服务，registry 五个工具齐、全只读；缺省仍是预约域。
- [ ] 4.3 ⚠ **真实仓库人工冒烟**——**未做，挂起等环境**（需内网 git + 已 clone 的真实服务仓库）。与切片 1 的 `VM_LOGS_*` 冒烟同属挂起项。**在此之前不得声称代码分析已可用。**
- [x] 4.4 ⚠ **验收表述**：离线测试证明的是「git 逻辑正确、jail 拦得住、异步不阻塞」；**「能不能定位到真实服务的源码」只有 4.3 能证明**。两者分开写。
- [x] 4.5 更新 `docs/oncall-bot-roadmap.md`：切片 2 完成、切片 3 待做。


## 5. 实现期的记账

- [x] 5.1 **本切片的实际范围比"移植 669 行"大**：参考系统的 `code-analysis` = repokit 定位 worktree + agent 用**自己的文件系统工具**去 grep/读（或派 explore 子 agent）。本项目的 harness 不给模型文件系统工具，只移植 repokit 会得到"返回了路径但读不了"的死工具。故新写了 `code_search` / `read_source` 两个受管束工具——**这是本切片最大的安全面，也是最该 review 的部分**。
- [x] 5.2 **`to_thread` 在这里是对的，与 `fix-embedding-timeout-blocking` 否决它不矛盾**：那边有原生异步替代（`aembed_query`）且 HTTP 连接会无限期泄漏；这边没有跨平台一致的替代（`create_subprocess_exec` 在 Windows 需 ProactorEventLoop），而 `subprocess.run(timeout=)` 会真正 kill 掉进程，把"取消不掉"的窗口封了顶。**线程池 + 子进程超时缺一不可**——只有前者会挂到子进程自然结束，只有后者会冻住事件循环。两条都有测试守。
- [x] 5.3 **不做 clone 是让只读策略自己说话**：若做成工具必须标 `dangerous=True`，会被 `policy.py` 直接拒。与其为它开例外或搬一套人工确认闸门，不如让 agent 根本没有这个能力。代价是首次分析某服务需运维介入一次——值守场景可接受，且比"让 bot 自己往磁盘拉代码"安全得多。
- [x] 5.4 用**真实 git** 跑测试（`git init` 造临时仓库 + 造 `prd-b` / `uat` 两个分支 + `--mirror` clone），不 mock git——要验的正是分支候选解析、worktree detached、TTL 跳过这些 git 行为，mock 掉等于什么也没验。
