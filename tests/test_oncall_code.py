"""源码定位与只读检索（change: oncall-domain-code）。

**用真实 git 驱动**（`git init` 造临时仓库 + 造分支），不 mock git——要验的正是分支
候选解析、worktree 创建这些 git 行为，mock 掉就等于什么也没验。

最重要的是 ④ 组的 jail：`read_source` 一旦能读任意路径，就是把 `.env` 里的
`VM_LOGS_PASSWORD` / `FEISHU_APP_SECRET` 暴露给模型。三类越界都必须被拒、且一个字节都不读。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import services.repo as repo


# --------------------------------------------------------------------------- #
# 临时 git 仓库
# --------------------------------------------------------------------------- #
def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, text=True, timeout=60)


@pytest.fixture
def repos_dir(tmp_path, monkeypatch):
    """造一个 repos/<service>/.git-mirror，含 prd-b / uat 两个分支。"""
    repos = tmp_path / "repos"
    (repos / "demo-svc").mkdir(parents=True)
    monkeypatch.setenv("ONCALL_REPOS_DIR", str(repos))

    # 先造一个普通仓库当作"远端"
    origin = tmp_path / "origin"
    origin.mkdir()
    _git("init", "-q", "-b", "prd-b", cwd=origin)
    _git("config", "user.email", "t@example.com", cwd=origin)
    _git("config", "user.name", "t", cwd=origin)
    (origin / "src").mkdir()
    (origin / "src" / "Handler.java").write_text(
        "package com.demo;\n"
        "class Handler {\n"
        "  void run() {\n"
        "    if (bad) throw new BizException(66302);\n"
        "  }\n"
        "  void other() {\n"
        "    throw new BizException(66302);\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    (origin / "README.md").write_text("demo\n", encoding="utf-8")
    _git("add", "-A", cwd=origin)
    _git("commit", "-qm", "init", cwd=origin)
    _git("branch", "uat", cwd=origin)

    # 镜像 clone 成 .git-mirror（与参考系统的布局一致）
    subprocess.run(["git", "clone", "-q", "--mirror", str(origin),
                    str(repos / "demo-svc" / ".git-mirror")],
                   check=True, capture_output=True, text=True, timeout=120)
    repo._last_sync.clear()
    return repos


# --------------------------------------------------------------------------- #
# ① 定位与分支候选
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_locate_resolves_env_branch_and_creates_worktree(repos_dir):
    result = await repo.locate_service_code("demo-svc", "prd", sync=False)

    assert result.status == "ready"
    assert result.branch == "prd-b"          # -b 变体优先
    assert result.head_sha
    assert Path(result.worktree_path).is_dir()
    assert (Path(result.worktree_path) / "src" / "Handler.java").is_file()


@pytest.mark.asyncio
async def test_prod_is_normalised_to_prd(repos_dir):
    """★ env 口径两边相反：日志侧 prod、代码侧 prd。service 层归一，别让模型记两套。"""
    result = await repo.locate_service_code("demo-svc", "prod", sync=False)

    assert result.status == "ready"
    assert result.env == "prd"


@pytest.mark.asyncio
async def test_bare_branch_name_is_fallback(repos_dir):
    """uat 只有裸名分支（没有 uat-b）→ 候选顺序里的兜底生效。"""
    result = await repo.locate_service_code("demo-svc", "uat", sync=False)

    assert result.status == "ready"
    assert result.branch == "uat"


@pytest.mark.asyncio
async def test_branch_not_found_returns_candidates(repos_dir):
    """★ 候选都不存在时必须带回已试列表——那是用户判断『是不是分支叫别的』的唯一依据。"""
    result = await repo.locate_service_code("demo-svc", "dev", sync=False)

    assert result.status == "branch_not_found"
    assert result.candidates_tried == ["dev-b", "dev"]
    assert result.ok is True      # 引导状态，不是错误


@pytest.mark.asyncio
async def test_unknown_service_returns_need_clone(repos_dir):
    """仓库没准备好是**正常引导状态**，不是异常——值守域不 clone（design D2）。"""
    result = await repo.locate_service_code("never-heard-of", "prd", sync=False)

    assert result.status == "need_clone"
    assert result.ok is True


@pytest.mark.asyncio
async def test_worktree_is_reused_not_recreated(repos_dir):
    first = await repo.locate_service_code("demo-svc", "prd", sync=False)
    second = await repo.locate_service_code("demo-svc", "prd", sync=False)

    assert first.worktree_path == second.worktree_path


@pytest.mark.asyncio
async def test_worktree_is_detached(repos_dir):
    """detached 而非 checkout 分支：分析用的工作区不该有『当前分支』的概念。"""
    result = await repo.locate_service_code("demo-svc", "prd", sync=False)

    rc = subprocess.run(["git", "-C", result.worktree_path, "symbolic-ref", "-q", "HEAD"],
                        capture_output=True, text=True, timeout=30)
    assert rc.returncode != 0, "HEAD 指向了分支，说明不是 detached"


@pytest.mark.asyncio
async def test_sync_is_skipped_within_ttl(repos_dir):
    """TTL 内跳过 fetch——否则每次分析都拉一次网络。"""
    first = await repo.locate_service_code("demo-svc", "prd", sync=True, ttl=60)
    second = await repo.locate_service_code("demo-svc", "prd", sync=True, ttl=60)

    assert first.synced is True
    assert second.synced is False


# --------------------------------------------------------------------------- #
# ② repo_dir 合法性（jail 第一层）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [
    "/etc", "../escape", "a/b", "a\\b", "..", ".", "",
])
def test_invalid_repo_dir_rejected(bad):
    assert repo.valid_repo_dir(bad) is False


@pytest.mark.parametrize("good", ["demo-svc", "ocs4", "a_b.c-1"])
def test_valid_repo_dir_accepted(good):
    assert repo.valid_repo_dir(good) is True


# --------------------------------------------------------------------------- #
# ③ 异步不阻塞
# --------------------------------------------------------------------------- #
@pytest.mark.timeout(30)
@pytest.mark.asyncio
async def test_git_calls_do_not_block_the_event_loop(repos_dir, monkeypatch):
    """★ git 是子进程、subprocess.run 同步阻塞——必须下沉线程池。

    实现若把 to_thread 去掉，这条不会失败而会挂死（心跳停），由 pytest-timeout 判失败。
    """
    real = repo._git_sync

    def slow(args, cwd, timeout):
        time.sleep(0.5)               # 模拟一次慢 git
        return real(args, cwd, timeout)

    monkeypatch.setattr(repo, "_git_sync", slow)

    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.ensure_future(repo.locate_service_code("demo-svc", "prd", sync=False))
    await asyncio.wait_for(heartbeat(), timeout=2.0)

    assert ticks == 5, "心跳停了 —— git 调用没下沉线程池"
    await task


def test_git_subprocess_carries_a_timeout():
    """子进程必须自带超时：只下沉线程池而无超时，卡住的 git 会永久占住线程池格子。"""
    import inspect

    src = inspect.getsource(repo._git_sync)
    assert "timeout=timeout" in src


# --------------------------------------------------------------------------- #
# ④ ★ jail —— 本切片最重要的一组
# --------------------------------------------------------------------------- #
def test_resolve_within_allows_normal_relative_path(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.java").write_text("x", encoding="utf-8")

    assert repo.resolve_within(tmp_path, "src/a.java").is_file()


def test_resolve_within_rejects_parent_escape(tmp_path):
    with pytest.raises(ValueError, match="越出工作区"):
        repo.resolve_within(tmp_path, "../../../etc/passwd")


def test_resolve_within_rejects_absolute_path(tmp_path):
    absolute = "C:\\Windows\\win.ini" if os.name == "nt" else "/etc/passwd"

    with pytest.raises(ValueError, match="绝对路径"):
        repo.resolve_within(tmp_path, absolute)


def test_resolve_within_rejects_symlink_pointing_outside(tmp_path):
    """★ 指向工作区外的符号链接必须被拦。

    这是 `resolve()` 之后再判断的理由——单纯拼接后看字符串前缀是拦不住 symlink 的。
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.env"
    secret.write_text("VM_LOGS_PASSWORD=hunter2", encoding="utf-8")

    worktree = tmp_path / "wt"
    worktree.mkdir()
    link = worktree / "sneaky"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("本平台创建符号链接需要额外权限（Windows 未开开发者模式）")

    with pytest.raises(ValueError, match="越出工作区"):
        repo.resolve_within(worktree, "sneaky")


@pytest.mark.asyncio
async def test_read_source_refuses_to_escape(repos_dir, tmp_path):
    """端到端：工具层拒绝越界，且**一个字节都不读**。"""
    from domains.oncall.tools import read_source

    secret = tmp_path / "secret.env"
    secret.write_text("FEISHU_APP_SECRET=leak", encoding="utf-8")

    with pytest.raises(Exception) as exc:
        await read_source.run({
            "service": "demo-svc", "env": "prd",
            "path": "../../../secret.env", "start_line": 1, "line_count": 10,
        })

    assert "leak" not in str(exc.value)


# --------------------------------------------------------------------------- #
# ⑤ 检索与阅读
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_code_search_returns_file_and_line(repos_dir):
    from domains.oncall.tools import code_search

    result = await code_search.run({
        "service": "demo-svc", "env": "prd", "pattern": "66302", "glob": "*.java",
    })

    assert result["hits"] == 2, "该错误码有两处抛出，必须都找出来"
    files = {h["file"] for h in result["results"]}
    assert files == {"src/Handler.java"}
    assert all(h["line"] > 0 and h["snippet"] for h in result["results"])


@pytest.mark.asyncio
async def test_code_search_truncation_is_flagged(repos_dir):
    from domains.oncall.tools import code_search

    result = await code_search.run({
        "service": "demo-svc", "env": "prd", "pattern": "66302",
        "glob": "*.java", "max_hits": 1,
    })

    assert result["hits"] == 1
    assert result["truncated"] is True, "截断了必须说，否则模型会以为只有这一处"


@pytest.mark.asyncio
async def test_read_source_returns_requested_range(repos_dir):
    from domains.oncall.tools import read_source

    result = await read_source.run({
        "service": "demo-svc", "env": "prd",
        "path": "src/Handler.java", "start_line": 2, "line_count": 3,
    })

    assert result["start_line"] == 2
    assert result["end_line"] == 4
    assert result["total_lines"] == 9        # 带上 total 才知道要不要接着读
    assert "class Handler" in result["content"]


def test_read_source_line_count_is_capped():
    from domains.oncall.tools.schemas import ReadSourceArgs
    from pydantic import ValidationError

    assert ReadSourceArgs(service="s", env="prd", path="a", line_count=200)
    with pytest.raises(ValidationError):
        ReadSourceArgs(service="s", env="prd", path="a", line_count=201)


@pytest.mark.asyncio
async def test_tools_report_guide_status_instead_of_silent_failure(repos_dir):
    """仓库没准备好时，检索工具要给出**可操作的**说明，且明确不许去别处找。"""
    from domains.oncall.tools import code_search

    with pytest.raises(Exception) as exc:
        await code_search.run({"service": "no-such-svc", "env": "prd", "pattern": "x"})

    message = str(exc.value)
    assert "need_clone" in message
    assert "不要在本机其他目录寻找源码" in message


# --------------------------------------------------------------------------- #
# ⑥ 值守域没有写代码的能力
# --------------------------------------------------------------------------- #
def test_oncall_has_no_write_capability():
    """★ 能力边界：这类工具压根不存在（与「分发闸门拒绝 dangerous」互补）。"""
    from domains import load_domain

    names = {t.name for t in load_domain("oncall").tools}

    for forbidden in ("clone", "commit", "push", "checkout", "patch", "apply", "write"):
        assert not any(forbidden in n for n in names), f"值守域出现了写操作工具：{names}"
    assert all(t.dangerous is False for t in load_domain("oncall").tools)


# --------------------------------------------------------------------------- #
# ⑦ 真实仓库验证发现的三处（2026-08-03）
# --------------------------------------------------------------------------- #
@pytest.fixture
def multi_service_repos(tmp_path, monkeypatch):
    """造一个**多服务同仓**的场景——真实的 mt-tools-v2 就是这样。

    分支：`SvcA/prd`、`SvcB/prd`（两个服务各自的 prd）、以及一个裸 `dev`
    （属于第三方，不该被任何服务的 dev 回退捡到）。
    """
    repos = tmp_path / "repos"
    (repos / "shared").mkdir(parents=True)
    monkeypatch.setenv("ONCALL_REPOS_DIR", str(repos))

    origin = tmp_path / "origin"
    origin.mkdir()
    _git("init", "-q", "-b", "SvcA/prd", cwd=origin)
    _git("config", "user.email", "t@e.com", cwd=origin)
    _git("config", "user.name", "t", cwd=origin)
    (origin / "a.txt").write_text("svcA code\n", encoding="utf-8")
    _git("add", "-A", cwd=origin)
    _git("commit", "-qm", "a", cwd=origin)
    _git("branch", "SvcB/prd", cwd=origin)
    _git("branch", "dev", cwd=origin)

    subprocess.run(["git", "clone", "-q", "--mirror", str(origin),
                    str(repos / "shared" / ".git-mirror")],
                   check=True, capture_output=True, text=True, timeout=120)
    (repos / "registry.json").write_text(json.dumps({
        "svca": {"repo_dir": "shared", "env_branches": {"prd": "SvcA/prd"}},
        "svcb": {"repo_dir": "shared", "env_branches": {"prd": "SvcB/prd"}},
    }), encoding="utf-8")
    repo._last_sync.clear()
    return repos


@pytest.mark.asyncio
async def test_per_service_branch_mapping_beats_global_candidates(multi_service_repos):
    """★ 全局候选列表不够用——真实仓库的环境分支是 `prd-ocs-ha`、`OCS5/prd` 这类。"""
    result = await repo.locate_service_code("svca", "prd", sync=False)

    assert result.status == "ready"
    assert result.branch == "SvcA/prd"      # 用了 registry 里声明的，不是全局候选 prd-b/prd


@pytest.mark.asyncio
async def test_multi_service_same_repo_do_not_share_worktree(multi_service_repos):
    """★ 同仓多服务不得撞车。

    修复前 worktree 是 `env-<env>`，svca 与 svcb 的 prd 会抢同一个目录——后来者把
    前者 checkout 走，**两个服务读到同一份代码而毫无察觉**。改为按分支命名后天然正确。
    """
    a = await repo.locate_service_code("svca", "prd", sync=False)
    b = await repo.locate_service_code("svcb", "prd", sync=False)

    assert a.worktree_path != b.worktree_path, "两个服务共用了同一个 worktree"
    assert (Path(a.worktree_path) / "a.txt").is_file()
    assert (Path(b.worktree_path) / "a.txt").is_file()


@pytest.mark.asyncio
async def test_declared_mapping_does_not_fall_back(multi_service_repos):
    """★ 声明了映射就以它为准，**不回退**到全局候选。

    修复前：svca 没配 dev → 回退到全局候选 → 捡到仓库里那个属于第三方的裸 `dev`
    分支，模型拿到错误的源码而毫不知情。比 branch_not_found 糟得多。
    """
    result = await repo.locate_service_code("svca", "dev", sync=False)

    assert result.status == "branch_not_found"
    assert result.branch is None
    assert "没有声明" in (result.error or ""), "空候选列表对用户没信息量，要说清是配置缺失"
    assert "prd" in (result.error or ""), "要列出已声明的环境，用户才知道能用什么"


@pytest.mark.asyncio
async def test_no_mapping_still_uses_global_candidates(repos_dir):
    """没声明映射的服务仍走全局候选——向后兼容，不逼所有仓库都写 registry。"""
    result = await repo.locate_service_code("demo-svc", "prd", sync=False)

    assert result.status == "ready"
    assert result.branch == "prd-b"
