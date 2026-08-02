"""源码定位与只读检索工具（OnCall 值守域）。

三个工具：`locate_service_code`（定位）、`code_search`（检索）、`read_source`（阅读）。
全部 `dangerous=False`——值守域**没有**任何写代码的能力（连 clone 都没有，见
change `oncall-domain-code` 的 design D2）。

⚠ **本模块最需要 review 的是 jail**：`read_source` 一旦能读任意路径，就是把 `.env` 里的
`VM_LOGS_PASSWORD` / `FEISHU_APP_SECRET` 直接暴露给模型。三重约束：

1. 入参只有 service + env + **相对路径**，没有绝对路径入口；
2. `resolve_within` 在 **resolve 之后**判断是否仍在工作区子树内（故挡得住 symlink）；
3. service 层的 `valid_repo_dir` 保证工作区本身不落到 `repos/` 外。

第 2、3 条是**两层独立实施**的——它们未来可能被独立修改，任一层被改坏时另一层仍拦得住。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from domains.oncall.tools.schemas import (
    CodeSearchArgs,
    LocateServiceCodeArgs,
    ReadSourceArgs,
)
from harness.tools.base import Tool

# 检索时跳过的目录（噪声大、几乎不含业务源码）。
_SKIP_DIRS = {".git", "node_modules", "target", "build", "dist", "__pycache__", ".idea", ".vscode"}
_MAX_FILE_BYTES = 2_000_000     # 超过即跳过：多半是二进制或生成物


async def _require_worktree(service: str, env: str) -> Path:
    """定位工作区；未就绪时抛出**带引导信息**的错误。

    错误会经 agent loop 吞成「工具执行失败」回灌给模型——那正是我们要的：模型看到
    「仓库还没准备好」就该去告诉用户找运维，而不是在别处乱找。
    """
    from services.repo import locate_service_code

    result = await locate_service_code(service, env)
    if result.status != "ready":
        raise RuntimeError(
            f"源码工作区未就绪（status={result.status}，service={service}，env={env}）。"
            + (f" 已尝试的分支：{result.candidates_tried}。" if result.candidates_tried else "")
            + " 请如实告知用户：仓库尚未在本地准备好或分支名不符，"
            "需要运维先把仓库 clone 到 repos/ 下——**不要在本机其他目录寻找源码**。"
        )
    return Path(result.worktree_path or "")


# --------------------------------------------------------------------------- #
# locate_service_code
# --------------------------------------------------------------------------- #
async def _locate_handler(args: LocateServiceCodeArgs) -> dict[str, Any]:
    from services.repo import locate_service_code

    result = await locate_service_code(args.service, args.env, sync=args.sync)
    return result.to_dict()


locate_service_code_tool = Tool(
    name="locate_service_code",
    description=(
        "定位某个服务在某环境下的源码工作区，返回工作区是否就绪、所在分支与 HEAD。\n"
        "env 用 dev / uat / stg / prd——注意与日志查询相反：**日志侧写 prod，代码侧写 prd**"
        "（本工具会自动归一，两种都收）。\n"
        "\n"
        "返回的 status 有几种是**正常引导状态**、不是错误：\n"
        "- `need_clone`：该服务的仓库还没在本地准备好。如实告诉用户需要运维先 clone，"
        "**绝不去本机其他目录找 checkout**。\n"
        "- `branch_not_found`：该环境的候选分支都不存在，结果里带回已试候选名——"
        "把它列给用户，问是不是分支叫别的。\n"
        "定位成功后用 code_search / read_source 在工作区内检索与阅读。"
    ),
    args_schema=LocateServiceCodeArgs,
    handler=_locate_handler,
)


# --------------------------------------------------------------------------- #
# code_search
# --------------------------------------------------------------------------- #
def _search_sync(worktree: Path, pattern: str, glob: str, context: int, max_hits: int) -> list[dict]:
    """在工作区内逐文件搜——同步实现，由调用方下沉线程池。"""
    import re as _re

    regex = _re.compile(pattern)
    hits: list[dict] = []
    for path in sorted(worktree.rglob(glob)):
        if len(hits) >= max_hits:
            break
        if not path.is_file() or any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines):
            if len(hits) >= max_hits:
                break
            if not regex.search(line):
                continue
            lo = max(0, idx - context)
            hi = min(len(lines), idx + context + 1)
            hits.append({
                "file": path.relative_to(worktree).as_posix(),
                "line": idx + 1,
                "snippet": "\n".join(lines[lo:hi]),
            })
    return hits


async def _search_handler(args: CodeSearchArgs) -> dict[str, Any]:
    worktree = await _require_worktree(args.service, args.env)
    # 逐文件读是阻塞 IO，与 git 子进程同理下沉线程池——工作区可能有上万个文件。
    hits = await asyncio.to_thread(
        _search_sync, worktree, args.pattern, args.glob, args.context_lines, args.max_hits
    )
    return {
        "service": args.service,
        "env": args.env,
        "pattern": args.pattern,
        "hits": len(hits),
        "truncated": len(hits) >= args.max_hits,
        "results": hits,
    }


code_search = Tool(
    name="code_search",
    description=(
        "在已定位的服务源码工作区内按正则检索，返回每处命中的 `文件:行号 + 片段`"
        "（含上下文行）。\n"
        "\n"
        "【定位抛出点的方法（重要）】给某个错误码/错误信息找抛出位置时，"
        "**先全局检索出所有抛出处**（通常不止一处），列出各自触发条件，"
        "**再用日志证据逐一排除**——绝不只取『离嫌疑调用最近的那一处』就开始论证。"
        "枚举完仍凭直觉押注等于白枚举。\n"
        "\n"
        "结果条数有上限，`truncated` 为真时说明还有更多命中，应收窄 pattern 或 glob 重查。"
    ),
    args_schema=CodeSearchArgs,
    handler=_search_handler,
)


# --------------------------------------------------------------------------- #
# read_source
# --------------------------------------------------------------------------- #
def _read_sync(worktree: Path, rel_path: str, start: int, count: int) -> dict[str, Any]:
    from services.repo import resolve_within

    # ★ jail：resolve 之后再判是否在子树内——故 `../`、绝对路径、指向外部的符号链接
    #   三类都拦得住。越界时**一个字节都不读**。
    target = resolve_within(worktree, rel_path)
    if not target.is_file():
        raise FileNotFoundError(f"工作区内不存在该文件：{rel_path}")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    lo = max(0, start - 1)
    chunk = lines[lo:lo + count]
    return {
        "file": rel_path,
        "start_line": lo + 1,
        "end_line": lo + len(chunk),
        "total_lines": len(lines),
        "content": "\n".join(chunk),
    }


async def _read_handler(args: ReadSourceArgs) -> dict[str, Any]:
    worktree = await _require_worktree(args.service, args.env)
    return await asyncio.to_thread(
        _read_sync, worktree, args.path, args.start_line, args.line_count
    )


read_source = Tool(
    name="read_source",
    description=(
        "读取已定位工作区内某个源码文件的指定行段。path 是**相对于工作区的路径**"
        "（如 `src/main/java/com/foo/Bar.java`），绝对路径会被拒绝。\n"
        "必须给 start_line 与 line_count（上限 200 行）——**不提供『读整个文件』**："
        "源码动辄数千行，整读既昂贵又淹没关键信息。先用 code_search 找到行号，再读它周围。\n"
        "返回里带 total_lines，据此判断要不要接着往下读。"
    ),
    args_schema=ReadSourceArgs,
    handler=_read_handler,
)
