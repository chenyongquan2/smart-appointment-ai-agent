#!/usr/bin/env python
"""OnCall 值守域的真实环境冒烟（第 3 期切片 1 与 2 的收尾验证）。

**为什么需要它**：离线测试证明的是「请求构造正确、jail 拦得住、异步不阻塞、失败分类
正确」；证明不了**「查得对不对」**——那需要真实凭据与内网可达性，CI 与开发机都没有。
在跑通本脚本之前，日志查询与代码分析**不得声称已可用**。

用法（在项目根）：

    # 先在 .env 里填好 VM_LOGS_URL / VM_LOGS_USER / VM_LOGS_PASSWORD
    # 若要验代码分析，再把某个服务仓库 clone 进 repos/（见下方 B 段说明）
    uv run python scripts/oncall_smoke.py

    # 只验其中一项
    uv run python scripts/oncall_smoke.py --only vlog
    uv run python scripts/oncall_smoke.py --only repo --service <服务名> --env prd

**不打印任何凭据**：结果里的错误信息经 `services.vlog.redact` 脱敏；本脚本自身也只
打印"已配置/未配置"，绝不回显值。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

OK = "  ✅"
NO = "  ❌"
WARN = "  ⚠️ "


def _mask(name: str) -> str:
    """只报"配没配"，绝不回显值。"""
    return "已配置" if os.getenv(name, "").strip() else "**未配置**"


# --------------------------------------------------------------------------- #
# A. 日志查询（切片 1 的 tasks 5.3）
# --------------------------------------------------------------------------- #
async def smoke_vlog(term: str) -> bool:
    from services.vlog import query_logs, resolve_targets

    print("\n" + "=" * 66)
    print("A. 日志查询冒烟（切片 1）")
    print("=" * 66)
    for key in ("VM_LOGS_URL", "VM_LOGS_USER", "VM_LOGS_PASSWORD"):
        print(f"  {key}: {_mask(key)}")

    if not all(os.getenv(k, "").strip() for k in ("VM_LOGS_URL", "VM_LOGS_USER", "VM_LOGS_PASSWORD")):
        print(NO, "凭据不全，跳过。请在 .env 里补齐后重跑。")
        return False

    print(f"\n  探查目标（env→租户，已按租户去重）：{resolve_targets(None)}")
    print(f"  检索词：{term!r}（发现模式，6h 窗，并发探全部环境）")

    result = await query_logs(term if term.startswith(('"', "_")) else f'"{term}"', window="6h", limit=3)

    print(f"\n  ok={result.ok}  total_hits={result.total_hits}  mode={result.mode}")
    for r in result.results:
        if r.error:
            print(f"{WARN}[{r.env}] 失败 kind={r.error_kind}")
            print(f"      {r.error[:160]}")
        else:
            print(f"{OK}[{r.env}] hits={r.hits} returned={len(r.lines)}")
            for line in r.lines[:1]:
                msg = str(line.get("_msg", ""))[:110]
                print(f"      {line.get('_time', '?')} | {msg}")
        print(f"      vmui: {r.vmui_url[:100]}")

    if result.hint:
        print(f"{WARN}提示：{result.hint}")

    # 判据：**至少一个 env 成功建立连接并返回结构化结果**。
    # 0 命中不算失败——那可能只是这个词最近确实没日志；连不上才是失败。
    if result.ok:
        print(f"\n{OK}**通过**：连接成功、返回结构化结果、vmui 链接已生成。")
        if result.total_hits == 0:
            print(f"{WARN}但 0 命中——换个确定近期出现过的关键词再跑一次更有说服力。")
        return True
    print(f"\n{NO}**未通过**：全部环境都失败。按上面的 error_kind 判断是网络/VPN 还是端点问题。")
    return False


# --------------------------------------------------------------------------- #
# B. 源码定位与检索（切片 2 的 tasks 4.3）
# --------------------------------------------------------------------------- #
async def smoke_repo(service: str, env: str, pattern: str) -> bool:
    from config.repo_config import resolve_repos_dir
    from services.repo import locate_service_code

    print("\n" + "=" * 66)
    print("B. 源码定位与只读检索冒烟（切片 2）")
    print("=" * 66)

    repos = resolve_repos_dir()
    print(f"  仓库目录：{repos}")
    if not repos.is_dir():
        print(NO, f"目录不存在。**agent 没有 clone 能力（那是写操作）**，")
        print("      需要先手工准备：")
        print(f"        mkdir -p {repos}/<服务名>")
        print(f"        git clone --mirror <git地址> {repos}/<服务名>/.git-mirror")
        return False

    # ⚠ **服务名 ≠ 目录名**：registry.json 把 service 映射到 repo_dir，一个仓库可能
    #   服务多个 service（真实的 mt-tools-v2 里住着 ocs5 / mttools 两个）。
    #   早先这里拿目录名当服务名，导致 `--service ocs5` 找不到、静默回退到 `mt-tools`。
    import json as _json

    registry_path = repos / "registry.json"
    services: list[str] = []
    if registry_path.is_file():
        try:
            services = sorted(_json.loads(registry_path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            services = []
    dirs = [p.name for p in repos.iterdir() if p.is_dir()]
    # 没进 registry 的目录也能用（service 名 = 目录名，走自动发现）
    known = services or dirs
    print(f"  registry 里的服务：{services or '（无 registry.json）'}")
    print(f"  repos/ 下的目录：  {dirs or '（空）'}")
    if not known:
        print(NO, "没有任何仓库，跳过。准备方式同上。")
        return False

    if service not in known:
        print(WARN, f"未指定或找不到服务 {service!r}，改用第一个：{known[0]}")
        service = known[0]

    print(f"\n  定位 service={service!r} env={env!r}（会 fetch 同步，TTL 内跳过）…")
    result = await locate_service_code(service, env)
    print(f"  status={result.status}  ok={result.ok}")

    if result.status != "ready":
        if result.candidates_tried:
            print(f"{WARN}已试分支：{result.candidates_tried}——都不存在，换个 env 或确认分支命名。")
        else:
            print(f"{WARN}{result.error or '仓库未就绪'}")
        return False

    print(f"{OK}worktree={result.worktree_path}")
    print(f"      branch={result.branch}  head={(result.head_sha or '')[:12]}  synced={result.synced}")

    from domains.oncall.tools import code_search, read_source

    print(f"\n  检索 pattern={pattern!r} …")
    found = await code_search.run({"service": service, "env": env, "pattern": pattern, "max_hits": 3})
    print(f"  hits={found['hits']} truncated={found['truncated']}")
    for h in found["results"][:2]:
        print(f"{OK}{h['file']}:{h['line']}")
        # 打**命中那一行**而非上下文首行：snippet 含前后各 3 行，首行常常不是命中行。
        matched = next(
            (ln for ln in h["snippet"].splitlines() if pattern.lower() in ln.lower()),
            (h["snippet"].splitlines() or [""])[0],
        )
        print(f"      {matched.strip()[:100]}")

    if found["hits"]:
        first = found["results"][0]
        chunk = await read_source.run({
            "service": service, "env": env, "path": first["file"],
            "start_line": max(1, first["line"] - 2), "line_count": 5,
        })
        print(f"\n  读取 {chunk['file']} 第 {chunk['start_line']}–{chunk['end_line']} 行"
              f"（全文 {chunk['total_lines']} 行）：")
        for line in chunk["content"].splitlines()[:5]:
            print(f"      {line[:100]}")

    # 顺带验一次 jail —— 真实 worktree 上的越界必须被拒
    print("\n  jail 检查（真实 worktree 上的越界尝试）…")
    try:
        await read_source.run({"service": service, "env": env, "path": "../../../.env",
                               "start_line": 1, "line_count": 5})
        print(NO, "**越界没被拦住** —— 这是严重问题，立刻停止使用并修复。")
        return False
    except Exception as exc:
        print(OK, f"越界被拒：{str(exc)[:80]}")

    print(f"\n{OK}**通过**：定位、检索、阅读、jail 四项都正常。")
    return True


# --------------------------------------------------------------------------- #
async def main() -> int:
    ap = argparse.ArgumentParser(description="OnCall 值守域真实环境冒烟")
    ap.add_argument("--only", choices=["vlog", "repo"], help="只跑其中一项")
    ap.add_argument("--term", default="ERROR", help="日志检索词（建议换成确定近期出现过的）")
    ap.add_argument("--service", default="", help="要定位的服务名")
    ap.add_argument("--env", default="prd", help="环境：dev/uat/stg/prd")
    ap.add_argument("--pattern", default="class", help="源码检索模式")
    args = ap.parse_args()

    results: dict[str, bool] = {}
    if args.only in (None, "vlog"):
        results["日志查询"] = await smoke_vlog(args.term)
    if args.only in (None, "repo"):
        results["源码定位与检索"] = await smoke_repo(args.service, args.env, args.pattern)

    print("\n" + "=" * 66)
    print("总结")
    print("=" * 66)
    for name, ok in results.items():
        print(f"  {'✅ 通过' if ok else '❌ 未通过'}  {name}")
    print("\n  通过的项即可在 tasks 里打勾；未通过的**不得**声称该能力可用。")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
