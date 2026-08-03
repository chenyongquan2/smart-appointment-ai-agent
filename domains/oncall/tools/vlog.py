"""vlog_query 工具：薄封装 `services/vlog.py`。

工具层只做「参数校验 + 转交」——三种给法归一成 LogsQL 这一步也在 service 里
（`build_term_query` / `parse_vmui_url`），本层不写查询构造逻辑。

`description` 是本工具最重要的部分：它是模型**构造查询那一刻**唯一会读的东西。
里面每一条都是参考系统真实事故换来的（见 change `oncall-domain-vlog` 的 design D3）。
"""

from __future__ import annotations

from typing import Any

from domains.oncall.tools.schemas import VlogQueryArgs
from harness.tools.base import Tool


async def _handler(args: VlogQueryArgs) -> dict[str, Any]:
    # 延迟 import：不在加载工具模块时就拉起 httpx 与凭据读取。
    from services.vlog import build_term_query, parse_vmui_url, query_logs

    env = args.env
    window = args.window
    limit = args.limit

    if args.term:
        logsql = build_term_query(args.term)
    elif args.logsql:
        logsql = args.logsql
    else:
        # vmui 链接自带 query / 时间窗 / 租户，解析后直接用——用户贴链接时通常没说 env。
        parsed = parse_vmui_url(args.url or "")
        logsql = parsed["query"]
        window = parsed.get("range_input") or window
        if parsed.get("limit"):
            limit = min(int(parsed["limit"]), 200)
        env = env or _env_from_account(parsed.get("account_id"))

    result = await query_logs(
        logsql,
        env=env,
        window=window,
        start=args.start,
        end=args.end,
        limit=limit,
        fields=args.fields,
    )
    return result.to_dict()


def _env_from_account(account_id: str | None) -> str | None:
    """accountId → env 标签。vmui 链接自带 accountID，据此免去让用户再说一次环境。

    租户 0 同时对应 dev 与 stg，无法反推唯一 env——此时返回 None（并发探查两者），
    **不猜**。这与"日志里没有的东西就是没查到"是同一条纪律。
    """
    from services.vlog import ACCOUNTS

    if not account_id:
        return None
    matches = [e for e, a in ACCOUNTS.items() if a == str(account_id)]
    return matches[0] if len(matches) == 1 else None


vlog_query = Tool(
    name="vlog_query",
    description=(
        "查询 VictoriaLogs 线上日志。三种给法任选其一：term（关键词/traceId）、"
        "logsql（自拼精确查询，用于下钻）、url（用户粘贴的 vmui 链接）。\n"
        "\n"
        "【查询怎么写才不超时】\n"
        "- 多关键词优先用 term 传多个词（自动拼引号精确 AND，走倒排索引）。"
        "**别上正则**：`_msg:~\"A\" AND _msg:~\"B\"` 这类双正则是全文逐行扫描，"
        "prod 数据量下即使缩到 6h 窗也会超时（真实事故：72h/24h/6h 连超 3 次、"
        "浪费 300+ 秒顶穿总超时）。\n"
        "- **时间窗是头号杠杆**：能窄就窄；已知环境就给 env。\n"
        "- **领头放最稀有的词**（traceId / 账号 / 订单号）；拿 INFO 这类高频词当主过滤"
        "等于全表扫。\n"
        "- 避开：大小写不敏感匹配、子串/短前缀通配、纯否定条件。\n"
        "- **环境用 env 参数指定，不要在 logsql 里写环境字段过滤**——日志里没有 `env` 这个"
        "字段，写 `env:PRD` 之类只会让查询变重或返回空（实测踩过）。\n"
        "- ⚠ **宽窗 + 正则会被工具直接拒绝**（不发请求、立刻返回改法）：那个组合必然超时。"
        "正则只在 window ≤ 1h 或给了 start 的精确窗里放行。\n"
        "- ⚠ **超时了要收窄，不要加宽**。实测踩过：追一个 traceId 时把窗口从 6h 拓到 7d，"
        "连续三次 60 秒超时、白等 3 分钟。查不到就换更稀有的词或缩小 env，别拓窗。\n"
        "- **多条件一律下推进查询**，别『查一个词回来在结果里筛另一个词』——返回的是样本，"
        "本地筛会因样本没覆盖而误判 0 命中（真实事故：命中 7205 条、本地筛出 0 条）。\n"
        "\n"
        "【时间与时区（最容易错的一处）】\n"
        "- 告警时间通常是北京时间，日志 _time 也是北京时间，两者**直接对齐、不要换算**。\n"
        "- 但 start/end 参数按 **UTC**（北京时间 −8h）。**优先用相对 window**，避开换算。\n"
        "- 告警晚于事件数十秒到数分钟：窗口要往告警时刻**之前**放宽 10~30 分钟。\n"
        "\n"
        "【返回值】\n"
        "results 里每个环境一项，含 hits（**总命中数**）、returned（**本次实际返回条数**）、"
        "lines（全字段日志对象，_msg 是完整原文、未截断）、vmui_url。\n"
        "hits 远大于 returned 时说明你只拿到样本，要收窄条件重查、而不是就样本下结论。\n"
        "⚠ **0 命中未必等于没有**：prod 数据量极大（6h 窗内约 50 亿行），宽窗查询有时"
        "「太重没算完」却返回 0。结果里出现 zero_hits_unreliable 字段、或 hint 提到"
        "可疑的 0 时，**必须收窄时间窗重查**（如 6h→30m），"
        "绝不能直接回复用户「该环境没有相关日志」。"
        "实测：prod 6h 窗查 ERROR 返回 0，同样的词 30m 窗有 55 条。\n"
        "**vmui_url 转给用户时逐字复制**，绝不自己拼改——真实的 query 是 urlencode 后的 "
        "LogsQL，凭印象重写必错。\n"
        "查询失败时返回 error 与 error_kind（timeout / connect_failed / http_error / other），"
        "如实转达给用户，**不要武断断定是 VPN 问题**。"
    ),
    args_schema=VlogQueryArgs,
    handler=_handler,
    # 只读查询：不设 dangerous → 默认 False。值守域的只读策略会拒绝任何 dangerous 工具。
)
