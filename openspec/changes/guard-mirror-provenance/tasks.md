## 1. 测试夹具（先做——没有能复现的坏 mirror，后面全是空谈）

- [ ] 1.1 在 [tests/test_oncall_code.py](../../../tests/test_oncall_code.py) 加夹具 `worktree_cloned_repos`：造三级「origin(bare) → 工作副本 → `git clone --mirror` 那份工作副本」，产出的 mirror 含 `refs/remotes/origin/*`。
- [ ] 1.2 夹具内复现**落后**：工作副本的 `refs/heads/{b}` 停在旧 commit，origin 上再推进若干 commit 后在工作副本 `git fetch`（只更新 `refs/remotes/origin/{b}`），再做 mirror。断言 mirror 里两个 ref 确实不同——**夹具自身先自证**，否则测试绿了也说明不了问题。
- [ ] 1.3 夹具内复现**分支只在 remotes 下**：某分支从未在工作副本建本地 ref，只存在于其 `refs/remotes/origin/` 下。

## 2. services/repo.py：探测与落后量

- [ ] 2.1 加 `_mirror_from_worktree(mirror) -> bool`：`for-each-ref --count=1 refs/remotes/` 非空即真（design D1）。按 `repo_dir` 缓存（D6）。探测失败/超时时返回假——降级方向保守，别把 git 抽风渲染成"你的 mirror 有问题"。
- [ ] 2.2 加 `_behind_count(mirror, branch) -> Optional[int]`：`rev-list --count refs/heads/{b}..refs/remotes/origin/{b}`；远端跟踪引用不存在时返回 `None`，不编数字（D2）。
- [ ] 2.3 `LocateResult` 增两个可选字段（来源可疑标记、落后数）+ 一条人话 `mirror_warning`；`to_dict()` 在字段为 `None` 时不输出，保证正规 mirror 的返回**一个字节都不变**。
- [ ] 2.4 文案分档（Risks 第 2 条）：落后 >0 用"⚠ 可能拿到旧代码 + 具体数字"，落后 0 用"来源不规范、当前恰好同步"。两处都写明判据（"该 mirror 下存在 refs/remotes/ 引用"），让人能自己核实。
- [ ] 2.5 `_ensure_worktree` 的 `branch_not_found` 分支：来源可疑时再查 `refs/remotes/origin/{cand}`，命中则在 `error` 里说明真实原因（D7）；正规 mirror 上跳过这次查询。
- [ ] 2.6 `locate_service_code` 的 `ready` 路径接线，把警示带进 `LocateResult`。**MUST NOT** 改 checkout 目标为 `refs/remotes/*`（D3）。

## 3. domains/oncall/tools/code.py：让警示抵达模型

- [ ] 3.1 `_require_worktree` 改为把警示一并带出（现在只返回 `Path`、丢掉整个 `LocateResult`）。
- [ ] 3.2 `code_search` / `read_source` 的返回里挂上警示——**这是本变更最容易做漏的地方**（design D5）：只改 locate 会留下"看起来做了、实际半数路径仍静默"的守卫。
- [ ] 3.3 `locate_service_code_tool` 的 description 补一句：拿到来源警示时**必须转达给用户**，不得自行忽略。

## 4. 测试

- [ ] 4.1 正规 mirror（既有 `repos_dir` 夹具）跑一遍定位：断言返回里**不含**任何来源字段——回归保护，证明没伤到正常路径。
- [ ] 4.2 落后场景：`ready` + 来源可疑 + 落后数等于夹具造的那个数（对具体数字断言，不只断言 truthy）。
- [ ] 4.3 落后 0 场景：仍标来源可疑、落后数为 0，且文案属"恰好同步"那一档。
- [ ] 4.4 分支只在 remotes 下：`branch_not_found` 且 `error` 说明了真实原因。
- [ ] 4.5 远端跟踪引用不存在：只报来源可疑、落后数为 `None`，不编数字。
- [ ] 4.6 **不绕行**：断言可疑来源下 worktree 的 HEAD 仍是 `refs/heads/{b}` 那个旧 commit，而不是远端那个新的（D3 的守护测试——没有它，日后有人"顺手修好"就没人拦得住）。
- [ ] 4.7 **警示覆盖全路径**：不调 locate 直接 `code_search` / `read_source`，断言返回里同样带警示（守 D5）。
- [ ] 4.8 探测失败降级：让探测子进程失败，断言按"探测不出"处理（不报警示、不抛错、定位照常）。

## 5. 验证与收尾

- [ ] 5.1 `uv run pytest` 全绿——成功静默、只报错。
- [ ] 5.2 [docs/oncall-bot-roadmap.md](../../../docs/oncall-bot-roadmap.md) 第 3 期把「建议的后续守卫（未做）」改为已做，并指向本 change。
- [ ] 5.3 如实记录**离线测试证明不了的部分**：真实的 `repos/` 下 mirror 现状（是否已按 roadmap 从正规远端重做）本变更不查证，需要时跑 `uv run python scripts/oncall_smoke.py --only repo` 在真实环境确认。
