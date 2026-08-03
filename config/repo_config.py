"""OnCall 值守域的源码仓库配置。

`repos/` 是**运维预先准备**的仓库存放地——本项目的 agent 不 clone（那是写操作，会被
值守域的只读策略拒绝，见 change `oncall-domain-code` 的 design D2）。
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "DEFAULT_GIT_TIMEOUT",
    "resolve_repos_dir",
    "resolve_git_timeout",
]

# git 子进程的超时。**必须显式**：subprocess 不设 timeout 就是无上限，
# 一次卡住的 fetch 会永久占住线程池的一个格子（见 design D1）。
DEFAULT_GIT_TIMEOUT = 120.0

_REPOS_ENV = "ONCALL_REPOS_DIR"
_TIMEOUT_ENV = "ONCALL_GIT_TIMEOUT_SECONDS"

# 缺省放仓库根下的 repos/（已 gitignore）。可配是因为部署环境可能要把它放到大盘符上。
_DEFAULT_REPOS_DIR = Path(__file__).resolve().parent.parent / "repos"


def resolve_repos_dir() -> Path:
    """仓库存放目录。"""
    raw = os.getenv(_REPOS_ENV, "").strip()
    return Path(raw).expanduser().resolve() if raw else _DEFAULT_REPOS_DIR


def resolve_git_timeout(explicit: float | None = None) -> float:
    """git 子进程超时：显式参数 > 环境变量 > 缺省。写错回落缺省，不让服务起不来。"""
    if explicit is not None:
        return float(explicit)
    raw = os.getenv(_TIMEOUT_ENV)
    if not raw:
        return DEFAULT_GIT_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_GIT_TIMEOUT
