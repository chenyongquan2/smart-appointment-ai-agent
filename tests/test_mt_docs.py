"""MT4/MT5 平台文档检索（change: oncall-domain-mtdocs）。

用**自造的小型 FTS 库**驱动——按真实 schema 造几行数据。这样做有两个用处：
既不依赖那两个真实库（468K/12M，不进版本库），又**把 schema 假设钉成了断言**：
将来真实库的表结构变了，这里会红，而不是等到线上查不出东西。

本切片是三片里唯一**不依赖内网或凭据**的，故测试能覆盖到端到端。
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

import services.mt_docs as mt
from config.mt_docs_config import MTDocsNotConfigured


# --------------------------------------------------------------------------- #
# 造库（schema 照抄真实库）
# --------------------------------------------------------------------------- #
def _build_mt4(path):
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE VIRTUAL TABLE toc_fts USING fts5(url, title, description, sections);
        CREATE VIRTUAL TABLE category_fts USING fts5(url, title, description, functions);
        CREATE VIRTUAL TABLE function_fts USING fts5(
            url, title, description, signature, parameters, remarks, return_value);
    """)
    c.execute("INSERT INTO function_fts VALUES (?,?,?,?,?,?,?)", (
        "https://docs.mql4.com/trading/ordersend", "OrderSend",
        "The main function used to open a market order or place a pending order.",
        "int OrderSend(string symbol, int cmd, double volume)",
        "symbol - symbol for trading", "Remarks about OrderSend",
        "Returns number of the ticket or -1"))
    c.execute("INSERT INTO function_fts VALUES (?,?,?,?,?,?,?)", (
        "https://docs.mql4.com/check/getlasterror", "GetLastError",
        "Returns the last error, such as ERR_NO_ERROR or ERR_INVALID_PRICE.",
        "int GetLastError()", "", "", "Returns error code"))
    c.execute("INSERT INTO category_fts VALUES (?,?,?,?)", (
        "https://docs.mql4.com/trading", "Trade Functions",
        "Functions for trading such as OrderSend", "OrderSend,OrderClose"))
    c.execute("INSERT INTO toc_fts VALUES (?,?,?,?)", (
        "https://docs.mql4.com/", "MQL4 Reference", "Top level", "Trading"))
    c.commit(); c.close()


def _build_mt5(path):
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE VIRTUAL TABLE api_class_fts USING fts5(
            name, description, sections, url, tokenize='porter unicode61');
        CREATE VIRTUAL TABLE api_method_fts USING fts5(
            class_name, method_name, title, description, signature_cpp, signature_net,
            parameters, return_value, remarks, url, tokenize='porter unicode61');
    """)
    c.execute("INSERT INTO api_method_fts VALUES (?,?,?,?,?,?,?,?,?,?)", (
        "CIMTOrder", "TradeRequest", "MT_RET_REQUEST_INVALID",
        "Returned when the trade request is invalid.",
        "int TradeRequest()", "int TradeRequest()", "none",
        "MT_RET_REQUEST_INVALID on failure", "See also MT_RET_OK",
        "https://mt5.example/api/traderequest"))
    c.execute("INSERT INTO api_class_fts VALUES (?,?,?,?)", (
        "CIMTOrder", "Order management class", "Methods", "https://mt5.example/api/order"))
    c.commit(); c.close()


@pytest.fixture
def docs_dir(tmp_path, monkeypatch):
    _build_mt4(tmp_path / "mt4docs.db")
    _build_mt5(tmp_path / "mt5api.db")
    monkeypatch.setenv("ONCALL_MT_DOCS_DIR", str(tmp_path))
    return tmp_path


# --------------------------------------------------------------------------- #
# ① ★ 查询字面量化（本切片最容易漏、真实使用必然触发的一处）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("OrderSend()", '"OrderSend"'),
    ("错误码 66302", '"错误码" "66302"'),
    ('a"b', '"a" "b"'),
    ("", ""),
    ("   ", ""),
])
def test_literalize_query(raw, expected):
    assert mt.literalize_query(raw) == expected


def test_literalize_neutralises_fts_operators():
    """FTS 操作符被当成普通词，不改变检索语义。"""
    out = mt.literalize_query("-foo OR bar")

    assert out.startswith('"')
    assert " OR " not in out.replace('"OR"', "")   # OR 变成了带引号的字面词


@pytest.mark.parametrize("query", [
    "OrderSend()", "MT_RET_REQUEST_*", 'say "hi"', "a-b-c", "(x)", "NOT y", "*",
])
@pytest.mark.asyncio
async def test_special_characters_never_raise_syntax_error(docs_dir, query):
    """★ 这组是本文件的核心。

    不做字面量化的话，这些输入会抛 `fts5: syntax error near "("`——而对调用方（模型）
    来说，**语法错误和空结果无法区分**，它只会看到"查不到"然后带着错误结论继续推理。
    """
    result = await mt.search_mt_docs("mt4", query)

    assert isinstance(result["hits"], int)      # 没抛异常即达成目的


# --------------------------------------------------------------------------- #
# ② 按平台分派
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_mt4_search_hits_function_table(docs_dir):
    result = await mt.search_mt_docs("mt4", "OrderSend")

    assert result["platform"] == "mt4"
    assert result["hits"] >= 1
    top = result["results"][0]
    assert top["table"] == "function_fts"        # 函数级最具体，排在分类之前
    assert top["title"] == "OrderSend"
    assert top["url"].startswith("https://docs.mql4.com")
    assert top["snippet"]


@pytest.mark.asyncio
async def test_mt5_search_hits_method_table(docs_dir):
    result = await mt.search_mt_docs("mt5", "MT_RET_REQUEST_INVALID")

    assert result["platform"] == "mt5"
    assert result["hits"] >= 1
    assert result["results"][0]["table"] == "api_method_fts"
    assert result["results"][0]["url"].startswith("https://mt5.example")


@pytest.mark.asyncio
async def test_platforms_do_not_bleed(docs_dir):
    """mt4 的库里查 mt5 的常量应当查不到——两个平台是分开的库、分开的表。"""
    result = await mt.search_mt_docs("mt4", "MT_RET_REQUEST_INVALID")

    assert result["hits"] == 0


@pytest.mark.asyncio
async def test_unknown_platform_rejected(docs_dir):
    with pytest.raises(ValueError, match="未知平台"):
        await mt.search_mt_docs("mt6", "x")


@pytest.mark.asyncio
async def test_limit_is_respected(docs_dir):
    result = await mt.search_mt_docs("mt4", "OrderSend", limit=1)

    assert result["hits"] == 1


# --------------------------------------------------------------------------- #
# ③ 未配置时明确失败（不返回空）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_unconfigured_raises_instead_of_empty(monkeypatch):
    """★ 空结果会被模型读成『查过了、文档里没有』，进而编造 API 语义。"""
    monkeypatch.delenv("ONCALL_MT_DOCS_DIR", raising=False)

    with pytest.raises(MTDocsNotConfigured) as exc:
        await mt.search_mt_docs("mt4", "OrderSend")

    assert "未配置" in str(exc.value)
    assert "不是文档里查不到" in str(exc.value)   # 明确区分配置问题与查无此项


@pytest.mark.asyncio
async def test_missing_db_file_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ONCALL_MT_DOCS_DIR", str(tmp_path))   # 目录在但文件不在

    with pytest.raises(MTDocsNotConfigured, match="缺失"):
        await mt.search_mt_docs("mt5", "x")


# --------------------------------------------------------------------------- #
# ④ 只读连接
# --------------------------------------------------------------------------- #
def test_connection_is_read_only(docs_dir):
    """★ 只读在**驱动层**保证，不靠『实现里没写 INSERT』的自觉。"""
    conn = mt._connect("mt4")
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO toc_fts VALUES ('u','t','d','s')")
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# ⑤ 不阻塞事件循环
# --------------------------------------------------------------------------- #
@pytest.mark.timeout(20)
@pytest.mark.asyncio
async def test_search_does_not_block_the_event_loop(docs_dir, monkeypatch):
    """sqlite 是同步阻塞的——虽然通常毫秒级，规则仍要一致（本项目已三次栽在这上面）。"""
    import time

    real = mt._search_sync

    def slow(platform, query, limit):
        time.sleep(0.4)
        return real(platform, query, limit)

    monkeypatch.setattr(mt, "_search_sync", slow)

    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.ensure_future(mt.search_mt_docs("mt4", "OrderSend"))
    await asyncio.wait_for(heartbeat(), timeout=2.0)

    assert ticks == 5, "心跳停了 —— sqlite 查询没下沉线程池"
    await task


# --------------------------------------------------------------------------- #
# ⑥ 工具层
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_tool_returns_results(docs_dir):
    from domains.oncall.tools import mt_docs_search

    result = await mt_docs_search.run({"platform": "mt4", "query": "OrderSend"})

    assert result["hits"] >= 1


def test_platform_is_required():
    from domains.oncall.tools.schemas import MTDocsSearchArgs
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MTDocsSearchArgs(query="OrderSend")          # 没给 platform
    with pytest.raises(ValidationError):
        MTDocsSearchArgs(platform="mt6", query="x")  # 非法 platform


def test_tool_description_separates_the_two_code_systems():
    """自研码与平台原生码是两套体系——description 必须讲清分流，否则模型会查错地方。"""
    from domains.oncall.tools import mt_docs_search

    desc = mt_docs_search.description
    assert "ocs4-returncode" in desc and "ocs5-returncode" in desc   # 自研码去哪查
    assert "mt-returncode" in desc                                    # 速查表先行
    assert "CMT4Processor" in desc and "CMT5Processor" in desc        # 怎么判平台
    assert "别猜" in desc


def test_oncall_now_has_six_read_only_tools():
    from domains import load_domain

    tools = load_domain("oncall").tools
    assert len(tools) == 6
    assert all(t.dangerous is False for t in tools)


# --------------------------------------------------------------------------- #
# ⑦ 真库验证发现并修掉的两处（回归守卫）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_snippet_comes_from_description_not_url(docs_dir):
    """★ 摘录必须取描述列，不能是 URL。

    真库验证时踩到的：`snippet(table, -1, ...)` 是「命中哪列取哪列」，而 url 列里
    常含关键词（查 Connect 会命中 `.../manager_api_connect/...`），于是摘录变成一串
    URL、毫无信息量。改成固定取描述列。
    """
    result = await mt.search_mt_docs("mt4", "OrderSend")

    top = result["results"][0]
    assert not top["snippet"].startswith("http"), "摘录取成了 URL"
    assert "market order" in top["snippet"] or "pending" in top["snippet"]


def test_tool_description_states_the_corpus_scope():
    """★ 必须写明收录的是 Manager API、不是 MQL 语言参考。

    真库验证时发现：拿 `OrderSend`（MQL4 语言函数）去查 mt4 库是 0 命中——因为那个库
    装的是 `CManagerInterface::*` 的 Manager API。模型若不知道这个边界，会把「不在
    本库范围内」误报成「该 API 不存在」，那是个自信的错误结论。
    """
    from domains.oncall.tools import mt_docs_search

    desc = mt_docs_search.description
    assert "Manager API" in desc
    assert "MQL" in desc
    assert "不是『没有这个 API』" in desc or "不是「没有这个 API」" in desc
