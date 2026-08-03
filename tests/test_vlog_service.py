"""VictoriaLogs 查询 service（change: oncall-domain-vlog）。

全程离线：用 `httpx.MockTransport` 注入假传输，**绝不触真实端点**。

守四类事：
1. **请求构造对不对**——两种模式的差异、env→租户映射与去重、时间窗写进 LogsQL 而非
   HTTP 参数（这条是参考实现记下的坑：该 VL 的 /hits 不按 HTTP 时间过滤）。
2. **异步不阻塞、多 env 并发**——照搬同步 urllib 就是第三次重演阻塞缺陷（前两次是
   知识库检索与技师专长匹配），故这里的守卫与 test_technician_matching_nonblocking 同款。
3. **失败如实分类且不泄凭据**——错误串会回灌进 LLM 上下文、随回复发进飞书群。
4. **vmui URL 往返一致**——它要逐字透传给用户，拼错就是给错链接。

⚠ 这些测试证明不了「查得对不对」：那需要真实凭据 + 内网，只能人工冒烟。
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

import services.vlog as vlog
from config.vlog_config import VLogCredentials

CREDS = VLogCredentials(url="https://vl.example.com", user="u", password="p")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)


def _ndjson(*objs) -> bytes:
    return "\n".join(json.dumps(o) for o in objs).encode()


# --------------------------------------------------------------------------- #
# ① 请求构造
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_discovery_mode_writes_window_into_logsql():
    """★ 发现模式把时间窗写进 LogsQL 的 `_time:`，而不是只靠 HTTP start 参数。

    参考实现的注释记了这个坑：本 VL 的 /hits **不按 HTTP start/end 过滤时间**（怎么传
    都全时段扫），只有 query 内的 `_time` 对两个端点都生效——否则会出现「/hits 报命中、
    /query 却 0 行」的口径不一致。搬迁时最容易「顺手简化」掉的正是这里。
    """
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = dict(pair.split("=", 1) for pair in request.content.decode().split("&"))
        seen.append({"path": request.url.path, "query": httpx.QueryParams(request.content.decode()).get("query")})
        if request.url.path.endswith("/hits"):
            return httpx.Response(200, content=json.dumps({"hits": [{"total": 7}]}).encode())
        return httpx.Response(200, content=_ndjson({"_time": "t", "_msg": "hello"}))

    async with _client(handler) as c:
        result = await vlog.query_logs("\"boom\"", env="prod", window="6h", credentials=CREDS, client=c)

    assert result.mode == "discovery"
    assert [s["path"] for s in seen] == ["/select/logsql/hits", "/select/logsql/query"]
    # 两个端点用的是同一个带 _time 的 query 串
    assert all("_time:6h" in s["query"] for s in seen)
    assert result.results[0].hits == 7


@pytest.mark.asyncio
async def test_range_mode_queries_directly():
    """给了 start 即精确窗模式：只打 /query，不先探 /hits。"""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, content=_ndjson({"_msg": "a"}, {"_msg": "b"}))

    async with _client(handler) as c:
        result = await vlog.query_logs("x", env="uat", start="2m", credentials=CREDS, client=c)

    assert result.mode == "range"
    assert paths == ["/select/logsql/query"]
    assert result.results[0].hits == 2           # 精确窗下 hits = 返回行数
    assert len(result.results[0].lines) == 2


@pytest.mark.asyncio
async def test_account_header_follows_env():
    """env→租户映射由 service 持有；调用方与模型都不需要知道租户编号。"""
    accounts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        accounts.append(request.headers["accountid"])
        return httpx.Response(200, content=_ndjson({"_msg": "x"}))

    async with _client(handler) as c:
        await vlog.query_logs("q", env="prd", start="1m", credentials=CREDS, client=c)   # prd → prod

    assert accounts == ["3"]


def test_targets_dedupe_by_account():
    """dev 与 stg 同租户 0，不去重会对同一租户查两遍。"""
    targets = vlog.resolve_targets(None)

    assert [a for _, a in targets] == ["3", "2", "0"]
    assert len(targets) == 3


def test_unknown_env_raises_with_options():
    with pytest.raises(ValueError) as exc:
        vlog.resolve_targets("prodd")

    assert "prodd" in str(exc.value) and "prod" in str(exc.value)


def test_term_query_uses_quoted_and_not_regex():
    """多词拼引号精确 AND（走倒排索引），不是正则。"""
    assert vlog.build_term_query(["4026299", "update_account"]) == '"4026299" AND "update_account"'
    assert "~" not in vlog.build_term_query(["a", "b"])


# --------------------------------------------------------------------------- #
# ② 异步不阻塞 + 多 env 并发
# --------------------------------------------------------------------------- #
@pytest.mark.timeout(20)
@pytest.mark.asyncio
async def test_query_does_not_block_the_event_loop():
    """★ 查询挂起期间事件循环必须仍能推进。

    实现若退回同步 urllib，这条不会失败而会**挂死**——循环被冻住，连它自己的
    asyncio 超时定时器都跑不了。pytest-timeout 走线程/信号，能把挂死变成明确失败。
    """
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(3600)
        return httpx.Response(200)

    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.01)
            ticks += 1

    async with _client(handler) as c:
        task = asyncio.ensure_future(
            vlog.query_logs("q", env="prod", credentials=CREDS, client=c)
        )
        await asyncio.wait_for(heartbeat(), timeout=2.0)
        task.cancel()

    assert ticks == 5


@pytest.mark.timeout(20)
@pytest.mark.asyncio
async def test_multiple_envs_are_probed_concurrently():
    """未指定 env 时三个租户必须并发探查，而非串行累加延迟。"""
    in_flight = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0.05)
            return httpx.Response(200, content=json.dumps({"hits": [{"total": 0}]}).encode())
        finally:
            in_flight -= 1

    started = time.monotonic()
    async with _client(handler) as c:
        result = await vlog.query_logs("q", credentials=CREDS, client=c)
    elapsed = time.monotonic() - started

    assert len(result.results) == 3
    assert peak == 3, f"并发峰值 {peak}，疑似串行"
    assert elapsed < 0.15, f"耗时 {elapsed:.3f}s，疑似串行"


# --------------------------------------------------------------------------- #
# ③ 失败分类、不泄凭据、不武断归因
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_timeout_is_classified_and_query_conditions_kept():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    async with _client(handler) as c:
        # ⚠ window 用 30m：宽窗 + 正则现在会被**预检拒掉、根本不发请求**
        #   （见 ⑥ 组，2026-08-03 实测催生）。这里要验的是传输层超时，故用窄窗放行。
        result = await vlog.query_logs('_msg:~"a"', env="prod", window="30m",
                                       credentials=CREDS, client=c)

    assert result.ok is False
    assert result.results[0].error_kind == "timeout"
    assert result.logsql == '_msg:~"a"'          # 查询条件保留，供用户判断
    assert result.results[0].vmui_url            # 失败也带 vmui 链接，用户可自己验证
    assert "正则" in (result.hint or "")          # 超时 + 含 ~ → 给确定性建议


@pytest.mark.asyncio
async def test_connect_failure_is_not_attributed_to_vpn():
    """只分类现象，不下结论。'connect_failed' 的含义是『连不上』，不是『VPN 断了』。"""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with _client(handler) as c:
        result = await vlog.query_logs("q", env="prod", credentials=CREDS, client=c)

    assert result.results[0].error_kind == "connect_failed"
    assert "VPN" not in (result.results[0].error or "")


@pytest.mark.asyncio
async def test_http_error_carries_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="no available upstream")

    async with _client(handler) as c:
        result = await vlog.query_logs("q", env="prod", credentials=CREDS, client=c)

    assert result.results[0].error_kind == "http_error"
    assert "503" in result.results[0].error


@pytest.mark.asyncio
async def test_one_env_failure_does_not_kill_the_others():
    """单个 env 失败要如实带回，但不该毁掉其它 env 的结果。"""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["accountid"] == "2":
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, content=json.dumps({"hits": [{"total": 1}]}).encode())

    async with _client(handler) as c:
        result = await vlog.query_logs("q", credentials=CREDS, client=c)

    kinds = {r.env: r.error_kind for r in result.results}
    assert kinds["uat"] == "connect_failed"
    assert kinds["prod"] is None
    assert result.ok is True     # 还有 env 成功，整体不算失败


def test_redact_strips_credentials_from_urls():
    """★ 错误串会回灌进 LLM 上下文并可能发进飞书群——凭据绝不能在里面。"""
    raw = "ConnectError for https://svcuser:s3cret@vl.internal/select/logsql/query?query=xx"

    cleaned = vlog.redact(raw)

    assert "svcuser" not in cleaned
    assert "s3cret" not in cleaned
    assert "vl.internal" in cleaned          # host 保留，它对排查有用
    assert "query=xx" not in cleaned         # query 一并去掉：长且无用


@pytest.mark.asyncio
async def test_error_result_is_redacted_end_to_end():
    """脱敏必须发生在 service 出口，不能只是个可选工具函数。"""
    creds = VLogCredentials(url="https://leak_user:leak_pw@vl.example.com", user="u", password="p")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed to connect to {request.url}", request=request)

    async with _client(handler) as c:
        result = await vlog.query_logs("q", env="prod", credentials=creds, client=c)

    assert "leak_user" not in result.results[0].error
    assert "leak_pw" not in result.results[0].error


def test_timeout_always_gets_actionable_advice():
    """超时**一律**给可操作建议——含正则给「改精确 AND」，不含正则给「收窄别加宽」。

    行为在 2026-08-03 改过：原来不含正则的超时什么都不说，于是模型继续加宽窗口、
    连吃三次 60 秒超时。沉默不是中立，它等于默许错误的下一步。
    """
    assert "正则" in (vlog.regex_hint('_msg:~"a"', "timeout") or "")
    assert "收窄" in (vlog.regex_hint('"a" AND "b"', "timeout") or "")   # 曾经是 None
    assert vlog.regex_hint('_msg:~"a"', "http_error") is None            # 非超时仍不提示


# --------------------------------------------------------------------------- #
# ④ vmui URL 往返
# --------------------------------------------------------------------------- #
def test_vmui_url_round_trip():
    """生成 → 解析 → 语义一致。它要逐字透传给用户，拼错就是给错链接。"""
    logsql = '"4026299" AND "update_account"'

    url = vlog.build_vmui_url("https://vl.example.com", "3", logsql, range_input="6h", limit=20)
    parsed = vlog.parse_vmui_url(url)

    assert parsed["query"] == logsql
    assert parsed["account_id"] == "3"
    assert parsed["range_input"] == "6h"
    assert parsed["relative_time"] == "last_6_hours"
    assert parsed["limit"] == 20


def test_vmui_params_live_in_fragment_not_query_string():
    """参数在 fragment（`#/?`）里——这正是必须由 service 解析、不让模型肉眼拆的原因。"""
    url = vlog.build_vmui_url("https://vl.example.com", "3", "x")

    assert "/select/vmui/?#/?" in url
    assert url.split("#", 1)[0].endswith("/select/vmui/?")


def test_parse_vmui_url_rejects_url_without_query():
    with pytest.raises(ValueError):
        vlog.parse_vmui_url("https://vl.example.com/select/vmui/?#/?view=group")


@pytest.mark.asyncio
async def test_result_separates_total_hits_from_returned_sample():
    """★ hits 是总数、returned 是样本数——混淆二者导致过真实误判（命中 7205、筛出 0）。"""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/hits"):
            return httpx.Response(200, content=json.dumps({"hits": [{"total": 7205}]}).encode())
        return httpx.Response(200, content=_ndjson(*[{"_msg": f"line{i}"} for i in range(20)]))

    async with _client(handler) as c:
        result = await vlog.query_logs("q", env="prod", limit=20, credentials=CREDS, client=c)

    d = result.to_dict()["results"][0]
    assert d["hits"] == 7205
    assert d["returned"] == 20
    assert d["hits"] != d["returned"]


@pytest.mark.asyncio
async def test_full_message_is_never_truncated():
    """截条数可以，**截正文不行**——堆栈与入参 JSON 都在 _msg 靠后，截断即丢根因。"""
    long_msg = "ERROR " + "x" * 5000 + " at com.foo.Bar(Bar.java:42)"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/hits"):
            return httpx.Response(200, content=json.dumps({"hits": [{"total": 1}]}).encode())
        return httpx.Response(200, content=_ndjson({"_msg": long_msg}))

    async with _client(handler) as c:
        result = await vlog.query_logs("q", env="prod", credentials=CREDS, client=c)

    assert result.results[0].lines[0]["_msg"] == long_msg
    assert result.results[0].lines[0]["_msg"].endswith("Bar.java:42)")


# --------------------------------------------------------------------------- #
# ⑤ 真实环境冒烟发现的缺陷：把「太重没算完」冒充「没有日志」区分开
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_slow_zero_is_flagged_as_unreliable(monkeypatch):
    """★ 真实环境冒烟发现的缺陷（2026-08-03）。

    prod 数据量极大（6h 窗内约 50 亿行），宽窗查询有时**返回 200 + 空结果而非报错**
    ——于是「查询太重没算完」和「真的没有日志」在结果上长得一模一样，模型会自信地
    告诉用户「prod 没有这个错误」。实测反证：同样的词 6h 窗返回 0、30m 窗有 55 条。

    区分依据是耗时（实测：真 0 秒回、可疑的 0 耗光超时）。
    """
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.35)                       # 慢
        return httpx.Response(200, content=json.dumps({"hits": [{"total": 0}]}).encode())

    # 把门槛压到 0.2s，让 0.35s 的响应落进"可疑"区间（真实门槛是超时上限的一半）
    monkeypatch.setattr(vlog, "_suspect_threshold", lambda: 0.2)

    async with _client(handler) as c:
        result = await vlog.query_logs("q", env="prod", credentials=CREDS, client=c)

    env = result.results[0]
    assert env.hits == 0
    assert env.zero_suspect is True
    d = env.to_dict()
    assert "zero_hits_unreliable" in d
    assert "不是真的没有日志" in d["zero_hits_unreliable"]
    assert "收窄时间窗" in (result.hint or ""), "可疑的 0 必须提到顶层 hint，模型才看得见"


@pytest.mark.asyncio
async def test_fast_zero_is_trusted(monkeypatch):
    """秒回的 0 就是真的 0——不能见 0 就喊狼来了，否则提示会被无视。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"hits": [{"total": 0}]}).encode())

    monkeypatch.setattr(vlog, "_suspect_threshold", lambda: 0.2)

    async with _client(handler) as c:
        result = await vlog.query_logs("q", env="prod", credentials=CREDS, client=c)

    assert result.results[0].zero_suspect is False
    assert "zero_hits_unreliable" not in result.results[0].to_dict()
    assert not result.hint


@pytest.mark.asyncio
async def test_nonzero_hits_never_flagged(monkeypatch):
    """有命中就不是「没算完」，再慢也不标可疑。"""
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.35)
        if request.url.path.endswith("/hits"):
            return httpx.Response(200, content=json.dumps({"hits": [{"total": 7}]}).encode())
        return httpx.Response(200, content=_ndjson({"_msg": "x"}))

    monkeypatch.setattr(vlog, "_suspect_threshold", lambda: 0.2)

    async with _client(handler) as c:
        result = await vlog.query_logs("q", env="prod", credentials=CREDS, client=c)

    assert result.results[0].zero_suspect is False


def test_tool_description_warns_about_unreliable_zero():
    """这条警告必须在 description 里——那是模型读结果时唯一的依据。"""
    from domains.oncall.tools import vlog_query

    desc = vlog_query.description
    assert "0 命中未必等于没有" in desc
    assert "zero_hits_unreliable" in desc


# --------------------------------------------------------------------------- #
# ⑥ 首次真实群聊暴露的三处（2026-08-03）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("logsql,window,start,rejected", [
    ('_msg:~"abc"',      "7d",  None, True),   # ★ 宽窗 + 正则 = 必然超时，拒
    ('_msg:~"abc"',      "6h",  None, True),
    ('_msg:~"abc"',      "30m", None, False),  # 窄窗放行——正则本身不是罪
    ('_msg:~"abc"',      "1h",  None, False),  # 恰好在门槛上
    ('_msg:~"abc"',      "7d",  "2m", False),  # 精确窗模式：调用方已知目标
    ('"abc" AND "def"',  "7d",  None, False),  # 无正则，宽窗也放行
    ('_msg:~"abc"',      "怪窗", None, True),   # 窗口解析不出来 → 保守拒（不猜）
])
def test_preflight_rejects_wide_window_regex(logsql, window, start, rejected):
    """★ 首次真实群聊的教训：description 里明写「别上 ~ 正则」，模型照样写了。

    实况：它发了 `{_msg:~"<traceId>"} and env:PRD` → VL 回 400
    （`unsupported operation "~" inside {...}`）；去掉花括号保留 `~` → **耗光 60 秒超时**。
    光靠 description 劝不住，故把这个必然超时的组合在发请求前就拒掉。
    """
    assert bool(vlog.preflight_reject(logsql, window, start)) is rejected


@pytest.mark.asyncio
async def test_rejected_query_sends_no_request():
    """被预检拒掉的查询**一个请求都不发**——省掉那 60 秒。"""
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, content=b"{}")

    async with _client(handler) as c:
        result = await vlog.query_logs('_msg:~"x"', env="prod", window="7d",
                                       credentials=CREDS, client=c)

    assert called["n"] == 0, "预检没拦住，请求发出去了"
    assert result.ok is False
    assert result.results == []
    assert "拒绝执行" in (result.hint or "")
    assert "term" in (result.hint or ""), "拒绝理由必须给出可操作的改法"


@pytest.mark.asyncio
async def test_timeout_hint_says_narrow_not_widen():
    """★ 超时的正确反应是收窄。

    实况：模型追 traceId 时把窗口 6h→2d→7d 一路拓宽，连续三次 60 秒超时、白等 3 分钟。
    原来的 hint 只在含正则时才给建议，不含正则的超时什么都不说——于是它继续加宽。
    """
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    async with _client(handler) as c:
        result = await vlog.query_logs('"rare-token"', env="prod", window="7d",
                                       credentials=CREDS, client=c)

    hint = result.hint or ""
    assert "收窄" in hint
    assert "不是加宽" in hint or "别拓窗" in hint or "继续加宽" in hint


def test_window_seconds_parses_or_refuses_to_guess():
    assert vlog.window_seconds("30m") == 1800
    assert vlog.window_seconds("6h") == 21600
    assert vlog.window_seconds("2d") == 172800
    assert vlog.window_seconds("nonsense") is None      # 不猜


def test_description_requires_explaining_approach_substitution():
    """用户明确要求用正则、bot 换成精确匹配时，要交代为什么。

    实测观察（2026-08-03）：用户说「用正则找一下…」，bot 直接用了 term 精确匹配——
    技术上换对了（稀有词走索引更快更准），但回复里只在括号里写了「精确匹配」、
    没说为何不照用户说的做。用户提了具体做法，换做法就该说明。
    """
    from domains.oncall.tools import vlog_query

    desc = vlog_query.description
    assert "用户明确要求用正则" in desc
    assert "交代" in desc or "说明" in desc


def test_description_warns_against_fabricated_env_filter():
    """模型编造了 `env:PRD` 字段过滤——日志里没这个字段，env 是工具参数。"""
    from domains.oncall.tools import vlog_query

    desc = vlog_query.description
    assert "env 参数指定" in desc
    assert "宽窗 + 正则会被工具直接拒绝" in desc
    assert "超时了要收窄" in desc


@pytest.mark.timeout(30)
@pytest.mark.asyncio
async def test_total_elapsed_is_bounded_not_just_per_read():
    """★ 实测发现的缺口（2026-08-03）：httpx 的 `timeout=60` 里 read 那项是**每次读取**
    的上限，不是整次请求的总时长。

    实证：同一个 traceId 在 prod 3d 窗 19 秒、**7d 窗 111 秒**——流式响应分多次读、
    每次都不超 60 秒，总时长就能翻倍。生产路径被 agent loop 的 Tool.timeout 截住了所以
    没出事，但 service 自己无界是不对的：冒烟脚本、评估、任何非 loop 调用方都没那层保护，
    而 zero_suspect 的门槛也是按「有总时长上限」校准的。

    这里用 asyncio.wait_for 是**成立**的——httpx 原生异步、在 await 点让得出控制权。
    （对比 services/repo.py 的 git 子进程：同步阻塞，wait_for 掐不断，只能线程池 +
    子进程自身 timeout。同一个判据、不同的手段。）
    """
    reads = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        # 每次「读」都很快，但总时长拖长——模拟流式慢响应
        for _ in range(20):
            reads["n"] += 1
            await asyncio.sleep(0.05)
        return httpx.Response(200, content=json.dumps({"hits": [{"total": 1}]}).encode())

    async with _client(handler) as c:
        result = await vlog.query_logs("q", env="prod", credentials=CREDS, client=c,
                                       timeout=0.3)   # 总时长上限 0.3s

    env = result.results[0]
    assert env.error_kind == "timeout"
    assert "总时长" in (env.error or ""), "要说清是总时长被切断，而不是 read 超时"
    assert reads["n"] < 20, "总时长上限没生效，请求跑完了"
