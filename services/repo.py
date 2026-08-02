"""服务源码定位 service（OnCall 值守域）—— 唯一碰 git 的确定性层。

移植自 `lark-oncall-bot/repokit.py`（669 行）的**确定性部分**：env→分支候选解析、
per-env 常驻 detached worktree、TTL 内跳过的 fetch、`repo_dir` 合法性校验、git 锁竞争
退避重试。

**没有移植**（刻意）：
- **clone** —— 写操作，会被值守域的只读策略拒绝。仓库由运维预先备好；这里落空只返回
  `need_clone` 引导状态（见 change `oncall-domain-code` 的 design D2）。
- registry 的增删改 —— 给 agent 一个"注册仓库地址"的工具等于让它改配置。这里只读。
- `parse-image` —— 它的产出是"建议的 git 地址"，只在 clone 流程里有用。
- 全部 CLI 引导逻辑 —— 本项目的形态是 service + tool，不是子命令。

**阻塞与超时**（design D1，务必读）：git 是子进程、`subprocess.run` 同步阻塞。
下沉 `asyncio.to_thread` **且**给子进程自身 `timeout=`，两者缺一不可：
- 只下沉线程池：协程能被取消，但线程里的子进程会一直跑到自然结束，线程池格子泄漏；
- 只设子进程超时：超时窗口内事件循环仍被冻住。

这与 `fix-embedding-timeout-blocking` 的 D2 **否决** `to_thread` 不矛盾——那边有原生
异步替代（`aembed_query`）且 HTTP 连接会无限期泄漏；这边没有跨平台一致的替代
（`create_subprocess_exec` 在 Windows 需要 ProactorEventLoop），而子进程的 `timeout=`
会真正 kill 掉进程，把"取消不掉"的窗口封了顶。

⚠ `Tool.timeout` 在此**不构成保护**：它靠 asyncio 取消，中断不了同步阻塞调用。
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config.repo_config import resolve_git_timeout, resolve_repos_dir

__all__ = [
    "ENV_BRANCH_CANDIDATES",
    "GUIDE_STATUS",
    "DEFAULT_SYNC_TTL",
    "LocateResult",
    "normalize_env",
    "valid_repo_dir",
    "locate_service_code",
    "resolve_within",
]

# 环境 → 候选分支：**带环境后缀的变体优先、裸名兜底**。
# 这是参考系统对公司分支命名实况的沉淀：裸 stg/prd 多为历史遗留僵尸分支，真正部署的
# 是 -b 变体（蓝绿）。都不存在则 branch_not_found，由用户判断（各仓库命名不统一）。
ENV_BRANCH_CANDIDATES: dict[str, list[str]] = {
    "dev": ["dev-b", "dev"],
    "uat": ["uat-b", "uat"],
    "stg": ["stg-b", "stg"],
    "prd": ["prd-b", "prd"],
}

# ⚠ env 口径两边相反：日志查询用 `prod`，git 分支用 `prd`。
# service 层做一次归一，别让模型记两套（design D5）。
_ENV_ALIASES = {"prod": "prd", "production": "prd", "staging": "stg", "development": "dev"}

DEFAULT_SYNC_TTL = 60.0     # 秒；TTL 内跳过 fetch，否则每次分析都拉一次网络

# 「正常引导」状态（等用户/运维介入），区别于 git 实际报错——前者 ok=True。
GUIDE_STATUS = {"ready", "need_clone", "branch_not_found", "bad_env", "need_git_url"}

_REPO_DIR_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_LOCK_HINTS = ("index.lock", "another git", ".lock'", "unable to create", "shallow.lock")


@dataclass
class LocateResult:
    """定位结果。``status`` 属 GUIDE_STATUS 时是可操作的正常分支，不是异常。"""

    status: str
    service: str
    env: Optional[str] = None
    worktree_path: Optional[str] = None
    branch: Optional[str] = None
    head_sha: Optional[str] = None
    synced: bool = False
    candidates_tried: Optional[list[str]] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status in GUIDE_STATUS

    def to_dict(self) -> dict:
        d = {"ok": self.ok, "status": self.status, "service": self.service}
        for k in ("env", "worktree_path", "branch", "head_sha", "candidates_tried", "error"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        if self.status == "ready":
            d["synced"] = self.synced
        return d


# --------------------------------------------------------------------------- #
# jail 第一层：repo_dir 只接受 repos/ 下的纯目录名
# --------------------------------------------------------------------------- #
def valid_repo_dir(repo_dir: str) -> bool:
    """``repo_dir`` 必须是 ``repos/`` 下的**纯目录名**。

    拒绝绝对路径、路径分隔符、``..``——worktree 绝不落到 ``repos/`` 外。这是 jail 的
    第一层；工具层还会再拦一次（两层独立实施，见 design D3）。

    参考系统在这上面吃过亏：2026-06-10 有过「绕道注册绝对路径 → 读码全被拒 →
    300 秒超时」的事故。
    """
    return bool(repo_dir) and bool(_REPO_DIR_RE.match(repo_dir)) and repo_dir not in (".", "..")


def resolve_within(root: Path, relative: str) -> Path:
    """把相对路径解析到 ``root`` 内，越界即抛。

    **检查发生在 ``resolve()`` 之后**——所以它也挡得住指向 root 外的符号链接
    （resolve 会跟随 symlink）。这一点是本函数存在的主要理由；单纯拼接再看字符串
    前缀是拦不住 symlink 的。
    """
    if Path(relative).is_absolute():
        raise ValueError(f"只接受相对路径，拒绝绝对路径：{relative!r}")
    root_resolved = root.resolve()
    target = (root_resolved / relative).resolve()
    if not target.is_relative_to(root_resolved):
        raise ValueError(f"路径越出工作区，拒绝访问：{relative!r}")
    return target


def normalize_env(env: str) -> str:
    """归一环境名。日志侧的 ``prod`` 在 git 侧是 ``prd``（design D5）。"""
    e = (env or "").strip().lower()
    return _ENV_ALIASES.get(e, e)


# --------------------------------------------------------------------------- #
# git 子进程（下沉线程池 + 子进程自带超时——两者缺一不可，见模块 docstring）
# --------------------------------------------------------------------------- #
def _git_sync(args: list[str], cwd: Optional[Path], timeout: float) -> tuple[int, str, str]:
    p = subprocess.run(
        ["git"] + args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,          # ← 到点 kill 子进程；没有它，线程池格子会被永久占住
    )
    return p.returncode, p.stdout.strip(), p.stderr.strip()


async def _git(args: list[str], cwd: Optional[Path] = None,
               timeout: Optional[float] = None) -> tuple[int, str, str]:
    """异步执行 git。**必须经 to_thread**——直接调用会冻住事件循环。"""
    return await asyncio.to_thread(_git_sync, args, cwd, resolve_git_timeout(timeout))


async def _git_lockretry(args: list[str], cwd: Optional[Path] = None, *,
                         retries: int = 8, wait: float = 0.7) -> tuple[int, str, str]:
    """对 git 自身的锁竞争退避重试。

    不维护自定义锁——顺应 git 的排他锁把并发 sync 串行化。多个 worktree detached 到
    同一 commit 互不冲突，故只有 refs/index 的锁需要处理。这段是参考系统在真实并发下
    踩出来的，照搬。
    """
    rc, out, err = await _git(args, cwd)
    for _ in range(retries):
        if rc == 0:
            break
        if not any(h in (err or "").lower() for h in _LOCK_HINTS):
            break
        await asyncio.sleep(wait)
        rc, out, err = await _git(args, cwd)
    return rc, out, err


# --------------------------------------------------------------------------- #
# registry（只读）
# --------------------------------------------------------------------------- #
def _registry_path() -> Path:
    return resolve_repos_dir() / "registry.json"


def _load_registry() -> dict:
    path = _registry_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 —— 映射表损坏不该让整个服务起不来
        return {}


def _entry_or_discover(service: str) -> Optional[dict]:
    """查映射表；落空时自动发现 ``repos/<service>/`` 下运维手工 clone 的仓库。

    **自动发现只看 ``repos/`` 内**——绝不向仓库外的本机目录找。找不到就是找不到，
    由上层如实告知用户，而不是在本机四处搜 checkout。
    """
    reg = _load_registry()
    entry = reg.get(service)
    if isinstance(entry, dict) and entry.get("repo_dir"):
        return entry
    if not valid_repo_dir(service):
        return None
    candidate = resolve_repos_dir() / service
    if (candidate / ".git").exists() or (candidate / ".git-mirror").exists():
        return {"repo_dir": service}
    return None


def _mirror_dir(repo_dir: str) -> Path:
    return resolve_repos_dir() / repo_dir / ".git-mirror"


def _env_worktree(repo_dir: str, env: str) -> Path:
    return resolve_repos_dir() / repo_dir / f"env-{env}"


# --------------------------------------------------------------------------- #
# 分支解析与 worktree
# --------------------------------------------------------------------------- #
async def _resolve_env_branch(mirror: Path, env: str) -> tuple[Optional[str], list[str]]:
    """按候选顺序找第一个存在的分支。返回 ``(branch|None, candidates)``。"""
    candidates = ENV_BRANCH_CANDIDATES.get(env, [])
    for cand in candidates:
        rc, _, _ = await _git(["-C", str(mirror), "rev-parse", "--verify", "--quiet",
                               f"refs/heads/{cand}"])
        if rc == 0:
            return cand, candidates
    return None, candidates


async def _ensure_worktree(repo_dir: str, env: str) -> tuple[str, Optional[Path], Optional[list[str]], Optional[str]]:
    """确保目标 worktree 存在。返回 ``(status, worktree, candidates, branch)``。"""
    mirror = _mirror_dir(repo_dir)
    if not mirror.exists():
        return ("need_clone", None, None, None)
    if env not in ENV_BRANCH_CANDIDATES:
        return ("bad_env", None, None, None)

    branch, candidates = await _resolve_env_branch(mirror, env)
    if branch is None:
        return ("branch_not_found", None, candidates, None)

    wt = _env_worktree(repo_dir, env)
    if wt.exists():
        return ("ready", wt, None, branch)

    wt.parent.mkdir(parents=True, exist_ok=True)
    # detached：分析用的 worktree 不该有「当前分支」的概念，避免任何形式的意外写入
    # 影响分支状态。
    rc, _, err = await _git_lockretry(
        ["-C", str(mirror), "worktree", "add", "--detach", str(wt), f"refs/heads/{branch}"]
    )
    if rc != 0:
        if wt.exists():        # 并发下已被另一协程创建
            return ("ready", wt, None, branch)
        return ("worktree_add_failed", None, None, branch)
    return ("ready", wt, None, branch)


async def _head_sha(wt: Path) -> Optional[str]:
    rc, head, _ = await _git(["-C", str(wt), "rev-parse", "HEAD"])
    return head if rc == 0 else None


_last_sync: dict[str, float] = {}


async def _sync(repo_dir: str, env: str, branch: str, wt: Path, ttl: float) -> bool:
    """fetch 到 mirror + 快进 worktree。TTL 内跳过，返回是否真的同步了。

    ``fetch`` 不改远端、不改历史、不产生提交，只更新本地镜像 refs——归类为
    「读远端 + 本地缓存」，故值守域允许。但 TTL 必须有，否则每次分析都拉一次网络。
    """
    key = f"{repo_dir}/{env}"
    now = time.monotonic()
    if now - _last_sync.get(key, 0.0) < ttl:
        return False

    mirror = _mirror_dir(repo_dir)
    rc, _, _ = await _git_lockretry(["-C", str(mirror), "fetch", "--prune", "origin"])
    if rc != 0:
        return False
    await _git_lockretry(["-C", str(wt), "checkout", "--detach", f"refs/heads/{branch}"])
    _last_sync[key] = now
    return True


async def locate_service_code(
    service: str,
    env: str,
    *,
    sync: bool = True,
    ttl: float = DEFAULT_SYNC_TTL,
) -> LocateResult:
    """service + env → 已就绪的只读工作区。

    未就绪时返回**引导状态**而非抛错：``need_clone``（仓库还没准备好）、
    ``branch_not_found``（带回已试候选，供用户判断是不是分支叫别的）、``bad_env``。
    这些都是可操作的正常分支。
    """
    normalized = normalize_env(env)
    entry = _entry_or_discover(service)
    if entry is None:
        return LocateResult(status="need_clone", service=service, env=normalized)

    repo_dir = entry["repo_dir"]
    if not valid_repo_dir(repo_dir):
        return LocateResult(
            status="bad_repo_dir", service=service, env=normalized,
            error=f"repo_dir 非法（须为 repos/ 下纯目录名）：{repo_dir!r}",
        )

    status, wt, candidates, branch = await _ensure_worktree(repo_dir, normalized)
    if status != "ready":
        return LocateResult(status=status, service=service, env=normalized,
                            candidates_tried=candidates)

    synced = await _sync(repo_dir, normalized, branch, wt, ttl) if sync else False
    return LocateResult(
        status="ready",
        service=service,
        env=normalized,
        worktree_path=str(wt),
        branch=branch,
        head_sha=await _head_sha(wt),
        synced=synced,
    )
