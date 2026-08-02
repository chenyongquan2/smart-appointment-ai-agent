"""VictoriaLogs 日志查询 service（OnCall 值守域）。

移植自 `lark-oncall-bot/probe.py`（381 行）。**语义照搬、形态重写**：

保留它踩坑换来的东西——env→租户映射、发现/精确窗两种模式、把时间窗写进 LogsQL 而非
HTTP 参数、错误四分类、正则超时提示、vmui URL 往返。

重写的部分：
- **传输层从同步 `urllib.request` 换成 `httpx.AsyncClient`**。这不是风格偏好：参考实现
  的超时默认 60 秒、且发现模式并发探所有 env，同步实现会把事件循环冻住一分钟——飞书
  长连接的收包与心跳一并停摆。这个缺陷本项目已经修过两次（知识库检索、技师专长匹配），
  照搬就是第三次。见 change `oncall-domain-vlog` 的 design D1。
- 输出从「单行 JSON 打 stdout」换成结构化返回值（本项目的工具是进程内 async handler）。
- **新增凭据脱敏**：参考实现没有这层，因为它的错误只进 worker 的 stdout；本项目的错误
  串会回灌进 LLM 上下文、并可能随回复发进飞书群，风险等级不同（design D6）。

凭据只在本层读取，**绝不进 LLM 上下文**——工具入参里没有任何凭据字段。
"""

from __future__ import annotations

import asyncio
import base64
import json
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from config.vlog_config import (
    VLogCredentials,
    load_vlog_credentials,
    resolve_vlog_timeout,
)

__all__ = [
    "ACCOUNTS",
    "ENV_ALIASES",
    "VLogError",
    "QueryResult",
    "EnvResult",
    "query_logs",
    "parse_vmui_url",
    "build_vmui_url",
    "resolve_targets",
    "classify_error",
    "regex_hint",
    "redact",
]

# env → accountId（多租户 header）。这是从参考实现保留下来的**唯一业务语义**：
# stg 取 pod-log-agent 租户 = 0，与 dev 同租户，故并发探查时要按 accountId 去重。
ACCOUNTS: dict[str, str] = {"prod": "3", "uat": "2", "dev": "0", "stg": "0"}
ENV_ALIASES: dict[str, str] = {"prd": "prod"}

# range_input → relative_time（组装 vmui 链接时带上，更像手点出来的）
_REL_TIME_MAP = {
    "5m": "last_5_minutes", "15m": "last_15_minutes", "30m": "last_30_minutes",
    "1h": "last_1_hour", "3h": "last_3_hours", "6h": "last_6_hours",
    "12h": "last_12_hours", "24h": "last_1_day", "1d": "last_1_day",
    "2d": "last_2_days", "7d": "last_7_days",
}

_HITS_PATH = "/select/logsql/hits"
_QUERY_PATH = "/select/logsql/query"


class VLogError(Exception):
    """查询失败。``kind`` 为四分类之一，供上层如实转达而非武断归因。"""

    def __init__(self, kind: str, message: str, *, status: Optional[int] = None) -> None:
        self.kind = kind
        self.status = status
        super().__init__(message)


@dataclass
class EnvResult:
    """单个环境的查询结果。"""

    env: str
    account: str
    hits: int = 0                       # 总命中数
    lines: list[dict[str, Any]] = field(default_factory=list)   # 实际返回的样本
    vmui_url: str = ""
    error: Optional[str] = None         # 该 env 失败时的（已脱敏）原始错误
    error_kind: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"env": self.env, "account": self.account, "vmui_url": self.vmui_url}
        if self.error is not None:
            d["error"] = self.error
            d["error_kind"] = self.error_kind
            return d
        d["hits"] = self.hits
        d["returned"] = len(self.lines)   # 与 hits 分开呈现：hits 是总数、lines 只是样本
        if self.lines:
            d["lines"] = self.lines
        return d


@dataclass
class QueryResult:
    """一次查询的完整结果（可能横跨多个环境）。"""

    ok: bool
    logsql: str
    mode: str                            # "discovery" | "range"
    results: list[EnvResult] = field(default_factory=list)
    total_hits: int = 0
    hint: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "ok": self.ok,
            "logsql": self.logsql,
            "mode": self.mode,
            "results": [r.to_dict() for r in self.results],
            "total_hits": self.total_hits,
        }
        if self.hint:
            d["hint"] = self.hint
        return d


# --------------------------------------------------------------------------- #
# 凭据脱敏（本项目新增，参考实现没有——见模块 docstring）
# --------------------------------------------------------------------------- #
def redact(text: str) -> str:
    """抹掉文本里 URL 的 userinfo 与 query。

    ``httpx`` 的异常串常含完整 URL；若 ``VM_LOGS_URL`` 是 ``https://user:pass@host`` 形式，
    不脱敏就会把凭据一路带进 LLM 上下文、再随回复发进飞书群。query 一并去掉是因为
    LogsQL 会被 urlencode 塞进去，长且无用。
    """
    if not text:
        return text

    def _clean(match_url: str) -> str:
        parts = urllib.parse.urlsplit(match_url)
        netloc = parts.netloc.rsplit("@", 1)[-1]   # 丢弃 userinfo
        return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, "", ""))

    out: list[str] = []
    for token in text.split():
        if "://" in token:
            try:
                out.append(_clean(token))
                continue
            except Exception:  # noqa: BLE001 —— 脱敏失败宁可丢弃整个 token，也不放行原串
                out.append("<url>")
                continue
        out.append(token)
    return " ".join(out)


# --------------------------------------------------------------------------- #
# vmui URL：解析 ↔ 组装（原样移植，含"参数在 fragment 里"这个坑）
# --------------------------------------------------------------------------- #
def parse_vmui_url(url: str) -> dict[str, Any]:
    """解析 vmui 浏览器 URL → dict。

    ⚠ 参数在 **fragment**（``#/?`` 之后）而非常规 query string——这是必须由 service 解析、
    不能让模型肉眼拆的原因。
    """
    frag = urllib.parse.urlsplit(url).fragment or ""
    if frag.startswith("/?"):
        frag = frag[2:]
    elif frag.startswith("?") or frag.startswith("/"):
        frag = frag[1:]
    pairs = urllib.parse.parse_qs(frag, keep_blank_values=True)

    def first(*keys: str) -> Optional[str]:
        for k in keys:
            v = pairs.get(k)
            if v:
                return v[0]
        return None

    query = first("query")
    if not query:
        raise ValueError("URL 里没有 query 参数（应在 fragment `#/?query=...` 中）")
    limit_raw = first("limit")
    return {
        "query": query,
        "account_id": first("accountID", "accountid") or "3",
        "range_input": first("g0.range_input"),
        "end_input": first("g0.end_input"),
        "relative_time": first("g0.relative_time"),
        "limit": int(limit_raw) if (limit_raw and limit_raw.isdigit()) else None,
    }


def build_vmui_url(
    host: str,
    account_id: str,
    logsql: str,
    *,
    range_input: str = "1h",
    end_input: Optional[str] = None,
    limit: int = 1000,
    step: str = "5s",
) -> str:
    """组装一个可点开的 vmui 浏览器 URL（参数放进 fragment）。

    ⚠ 生成后 **逐字透传**：工具层不得加工、模型转给用户时不得自行拼改。真实的 query 是
    urlencode 后的 LogsQL，凭印象重写必错（参考系统里有专门一段警告）。
    """
    parts = [
        "query=" + urllib.parse.quote(logsql, safe=""),
        "g0.range_input=" + range_input,
    ]
    if end_input:
        parts.append("g0.end_input=" + end_input)
    rel = _REL_TIME_MAP.get(range_input.lower())
    if rel:
        parts.append("g0.relative_time=" + rel)
    parts += [
        "view=group",
        "accountID=" + str(account_id),
        "projectID=0",
        "limit=" + str(limit),
        "step=" + step,
    ]
    return "%s/select/vmui/?#/?%s" % (host.rstrip("/"), "&".join(parts))


# --------------------------------------------------------------------------- #
# 目标解析与错误分类
# --------------------------------------------------------------------------- #
def resolve_targets(env: Optional[str]) -> list[tuple[str, str]]:
    """返回 ``[(env_label, account_id)]``。

    给了 env → 单个；没给 → 全部 env **按 accountId 去重**（dev 与 stg 同租户 0，
    不去重会对同一租户查两遍）。
    """
    if env:
        normalized = ENV_ALIASES.get(env.lower(), env.lower())
        if normalized not in ACCOUNTS:
            raise ValueError(f"未知环境 '{env}'。可选：{', '.join(sorted(ACCOUNTS))}（prd 是 prod 的别名）")
        return [(normalized, ACCOUNTS[normalized])]
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for e, a in ACCOUNTS.items():
        if a not in seen:
            seen.add(a)
            out.append((e, a))
    return out


def classify_error(exc: BaseException) -> str:
    """如实分类失败原因——只描述现象、**绝不武断归因 VPN**（判断权留给用户）。

    - ``timeout``：查询超时（查询重 / 网络慢 / 服务忙均可能）
    - ``connect_failed``：连不上端点（网络 / VPN / 端点不可达）
    - ``http_error``：服务端返回错误码
    - ``other``：其它
    """
    if isinstance(exc, VLogError):
        return exc.kind
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return "http_error"
    if isinstance(exc, httpx.TransportError):   # 连接/DNS/SSL 等
        return "connect_failed"
    return "other"


def regex_hint(logsql: str, kind: str) -> Optional[str]:
    """超时且查询用了正则过滤器（``~``）时给确定性建议——只提示、不替用户改写。

    踩过的坑（真实事故）：``_msg:~"A" AND _msg:~"B"`` 双正则在 prod 大数据量下连缩窗都
    超时，72h/24h/6h 连超 3 次、累计浪费 300+ 秒顶穿总超时。
    """
    if kind == "timeout" and logsql and "~" in logsql:
        return (
            "查询含正则过滤器（~），大数据量下触发全文逐行扫描、极易超时；"
            "多关键词组合请改引号精确 AND（如 \"A\" AND \"B\"，走倒排索引、量级更快）。"
        )
    return None


# --------------------------------------------------------------------------- #
# 传输层（async httpx —— 见模块 docstring 的 D1）
# --------------------------------------------------------------------------- #
def _auth_header(creds: VLogCredentials) -> str:
    raw = f"{creds.user}:{creds.password}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _form(logsql: str, *, start=None, end=None, **extra) -> list[tuple[str, str]]:
    p: list[tuple[str, str]] = [("query", logsql)]
    if start is not None:
        p.append(("start", str(start)))
    if end is not None:
        p.append(("end", str(end)))
    for k, v in extra.items():
        if v is not None:
            p.append((k, str(v)))
    return p


async def _post(
    client: httpx.AsyncClient,
    creds: VLogCredentials,
    path: str,
    account_id: str,
    form: list[tuple[str, str]],
    *,
    project_id: str = "0",
) -> bytes:
    resp = await client.post(
        creds.url.rstrip("/") + path,
        content=urllib.parse.urlencode(form).encode(),
        headers={
            "accountid": str(account_id),
            "projectid": str(project_id),
            "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
            "authorization": _auth_header(creds),
        },
    )
    if resp.status_code >= 400:
        raise VLogError(
            "http_error",
            f"VictoriaLogs HTTP {resp.status_code}: {resp.text[:500]}",
            status=resp.status_code,
        )
    return resp.content


def _parse_ndjson(raw: bytes) -> list[dict[str, Any]]:
    """每行解析为**全字段对象**（含 ``_time`` / ``_msg`` / pod 字段…），供下钻抽字段。

    坏行回 ``{"_raw": ...}`` 而非丢弃——排查时一条读不懂的日志也可能是线索。
    """
    out: list[dict[str, Any]] = []
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001
            out.append({"_raw": line})
    return out


async def _probe_one(
    client: httpx.AsyncClient,
    creds: VLogCredentials,
    env: str,
    account: str,
    logsql: str,
    *,
    window: str,
    start: Optional[str],
    end: Optional[str],
    limit: int,
    fields: Optional[list[str]],
) -> EnvResult:
    """查一个环境。异常在此吞成 EnvResult.error，**不冒泡**——单个 env 失败不该毁掉整次查询。"""
    range_input = window if start is None else "1h"
    result = EnvResult(
        env=env,
        account=account,
        vmui_url=build_vmui_url(creds.url, account, logsql,
                                range_input=range_input, end_input=end, limit=limit),
    )
    try:
        if start is not None:
            # 精确窗模式：直接 query（调用方已知目标，下钻场景）。hits 数 = 返回行数。
            raw = await _post(client, creds, _QUERY_PATH, account,
                              _form(logsql, start=start, end=end, limit=limit,
                                    fields=",".join(fields) if fields else None))
            objs = _parse_ndjson(raw)
            result.hits = len(objs)
            result.lines = objs
        else:
            # 发现模式：把窗口写进 LogsQL（`_time:<window>`），/hits 与 /query 用同一 query 串。
            # ⚠ 这个坑值得记：本 VL 的 /hits **不按 HTTP start/end 过滤时间**（怎么传都全时段
            # 扫），只有 query 内的 _time 过滤对两个端点都生效——否则会出现「/hits 报命中、
            # /query 却 0 行」的口径不一致。
            disc = f"{logsql} _time:{window}"
            hits_raw = await _post(client, creds, _HITS_PATH, account,
                                   _form(disc, start=window, step=window))
            hits_obj = json.loads(hits_raw)
            result.hits = sum(b.get("total", 0) for b in hits_obj.get("hits", []))
            if result.hits > 0:
                raw = await _post(client, creds, _QUERY_PATH, account,
                                  _form(disc, start=window, limit=limit,
                                        fields=",".join(fields) if fields else None))
                result.lines = _parse_ndjson(raw)
    except Exception as exc:  # noqa: BLE001 —— 单 env 失败要如实带回，不毁掉其它 env
        result.error_kind = classify_error(exc)
        result.error = redact(str(exc))
    return result


async def query_logs(
    logsql: str,
    *,
    env: Optional[str] = None,
    window: str = "6h",
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 20,
    fields: Optional[list[str]] = None,
    credentials: Optional[VLogCredentials] = None,
    timeout: Optional[float] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> QueryResult:
    """查询日志。未指定 env 时**并发**探查全部环境（按租户去重）。

    Args:
        logsql: 原始 LogsQL。
        env: 环境；``None`` 时并发探查全部。
        window: 相对时间窗（发现模式用）。
        start / end: 绝对时刻；给了 ``start`` 即进精确窗模式。**按 UTC**（VL 后端用 UTC）。
        limit: 单个环境返回的最大条数。注意这是**样本上限**，与总命中数是两回事。
        fields: 只取这些字段；``None`` 返回全字段对象（下钻的抓手）。
        credentials / timeout / client: 注入点，测试用（``client`` 传入即复用，不自建）。

    Returns:
        ``QueryResult``；单个 env 失败不会抛，而是记在该 env 的 ``error`` 上。
        全部 env 都失败时 ``ok=False``。
    """
    creds = credentials or load_vlog_credentials()
    targets = resolve_targets(env)
    mode = "range" if start is not None else "discovery"

    # trust_env=False：内网 host 走不通公司外网代理（参考实现是清空 *_PROXY 并设 no_proxy=*，
    # httpx 用这个开关等价且更干净——它同时忽略环境里的代理与 CA 配置）。
    owns_client = client is None
    http = client or httpx.AsyncClient(
        timeout=resolve_vlog_timeout(timeout),
        trust_env=False,
    )
    try:
        # 并发探查：串行会把延迟叠成 N × RTT，而日志查询单次就是秒级到分钟级。
        results = await asyncio.gather(*(
            _probe_one(http, creds, e, a, logsql,
                       window=window, start=start, end=end, limit=limit, fields=fields)
            for e, a in targets
        ))
    finally:
        if owns_client:
            await http.aclose()

    ok = any(r.error is None for r in results)
    total = sum(r.hits for r in results if r.error is None)
    first_err = next((r.error_kind for r in results if r.error_kind), None)
    return QueryResult(
        ok=ok,
        logsql=logsql,
        mode=mode,
        results=list(results),
        total_hits=total,
        hint=regex_hint(logsql, first_err or ""),
    )


def build_term_query(terms: list[str]) -> str:
    """把多个关键词拼成引号精确 AND —— **走倒排索引，别用正则**。

    这是参考系统 ``--term A B`` 的语义：``"A" AND "B"``。引号 phrase filter 走索引，
    正则 ``~`` 是全文逐行扫描，两者性能差一个量级（见 regex_hint 记的那次事故）。
    """
    return " AND ".join('"%s"' % t.replace('"', '\\"') for t in terms)
