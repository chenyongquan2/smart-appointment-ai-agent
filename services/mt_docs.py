"""MT4/MT5 平台文档检索 service（OnCall 值守域）。

复用参考系统现成的两个 SQLite FTS5 库——**不重建语料**，本仓只是使用方：

| 库 | FTS 表 | 行数 |
|---|---|---|
| `mt4docs.db`(468K) | `function_fts` / `category_fts` / `toc_fts` | 197 / 35 / 3 |
| `mt5api.db`(12M) | `api_method_fts` / `api_class_fts` | 4834 / 575 |

两边的 schema 与列名都不同（mt5 有 `signature_cpp`/`signature_net` 双签名，mt4 没有），
故**按平台分派、不做统一抽象**——抽象要么丢字段、要么变成一堆 Optional 的大杂烩
（见 change `oncall-domain-mtdocs` 的 design D3）。

⚠ 本模块两处最容易被漏掉的事，都写在对应函数的 docstring 里：
1. `_literalize` —— 用户的检索词必须字面量化，否则 `OrderSend()` 直接抛 FTS5 语法错误；
2. `mode=ro` —— 只读在驱动层保证，不靠"我们没写 INSERT"的自觉。
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from config.mt_docs_config import MTDocsNotConfigured, resolve_db_path

__all__ = ["PLATFORMS", "DocHit", "search_mt_docs", "literalize_query"]

PLATFORMS = ("mt4", "mt5")

# 每个平台要查的表，以及各表用哪些列拼标题 / 取摘录。
# 顺序即优先级：函数/方法级最具体，放前面。
# (表名, 标题列, 摘录列的**序号**)。
# ⚠ 摘录**固定取描述列**而非 snippet(table, -1, ...)：-1 是「命中哪列取哪列」，
# 而 url 列里常含关键词（如查 Connect 会命中 .../manager_api_connect/...），
# 于是摘录就变成一串 URL、毫无信息量。真库验证时踩到的。
_MT4_TABLES = (
    ("function_fts", "title", 2),    # url,title,description,signature,parameters,remarks,return_value
    ("category_fts", "title", 2),    # url,title,description,functions
    ("toc_fts", "title", 2),         # url,title,description,sections
)
_MT5_TABLES = (
    ("api_method_fts", "title", 3),  # class_name,method_name,title,description,...
    ("api_class_fts", "name", 1),    # name,description,sections,url
)
_TABLES = {"mt4": _MT4_TABLES, "mt5": _MT5_TABLES}

_WORD_RE = re.compile(r"[0-9A-Za-z_一-鿿]+")


@dataclass
class DocHit:
    """一条命中。``table`` 带上是为了让调用方看出命中的是函数级还是分类级。"""

    title: str
    snippet: str
    url: str
    table: str

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "snippet": self.snippet, "url": self.url, "table": self.table}


def literalize_query(raw: str) -> str:
    """把用户输入变成 FTS5 能安全执行的字面量查询。

    ★ **本模块最重要的一个函数**，不做它一定会在真实使用中炸。

    FTS5 的 MATCH 有自己的语法：``"`` 短语、``*`` 前缀、``-`` 排除、``()`` 分组、
    ``AND``/``OR``/``NOT`` 操作符。而排障时的检索词天然带这些字符——``OrderSend()``、
    ``MT_RET_REQUEST_*``、``ERR_NO_ERROR``。原样拼进去的结果是
    ``sqlite3.OperationalError: fts5: syntax error near "("``。

    对调用方（模型）而言，**语法错误和空结果是无法区分的**——它只会看到"查不到"，
    然后带着错误结论继续推理。所以这里把每个词单独加引号（内部 ``"`` 转义成 ``""``），
    空格连接（FTS5 里空格即 AND）：

        OrderSend()        → "OrderSend"
        MT_RET_REQUEST_*   → "MT_RET_REQUEST"
        错误码 66302        → "错误码" "66302"

    **代价**：调用方无法再使用 FTS 高级语法。这是刻意取舍——本工具的调用方是模型
    不是检索专家，"不必学语法、也不会被语法错误挡住"比保留高级语法有价值得多。
    （对比切片 1 的 `vlog_query` 做了相反选择：那边保留了原始 LogsQL 入口，因为
    查询语言本身是排障的核心技能、值得让模型学。）
    """
    words = _WORD_RE.findall(raw or "")
    if not words:
        return ""
    return " ".join('"%s"' % w.replace('"', '""') for w in words)


def _connect(platform: str) -> sqlite3.Connection:
    """只读打开。``mode=ro`` 让写在**驱动层**就不可能，而不是靠实现里没写 INSERT。"""
    path = resolve_db_path(platform)
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _search_sync(platform: str, query: str, limit: int) -> list[DocHit]:
    match = literalize_query(query)
    if not match:
        return []

    hits: list[DocHit] = []
    conn = _connect(platform)
    try:
        for table, title_col, snippet_col in _TABLES[platform]:
            if len(hits) >= limit:
                break
            remaining = limit - len(hits)
            # snippet() 取描述列的摘录；bm25 越小越相关（负值，越负越相关）。
            sql = (
                f"SELECT {title_col}, snippet({table}, {snippet_col}, '', '', ' … ', 24), url "
                f"FROM {table} WHERE {table} MATCH ? ORDER BY bm25({table}) LIMIT ?"
            )
            try:
                rows = conn.execute(sql, (match, remaining)).fetchall()
            except sqlite3.OperationalError:
                # 某张表缺列或库版本不同——跳过该表而非整次失败。
                # schema 假设有测试守着，这里只是运行期的兜底。
                continue
            for title, snippet, url in rows:
                hits.append(DocHit(
                    title=(title or "").strip(),
                    snippet=" ".join((snippet or "").split()),
                    url=(url or "").strip(),
                    table=table,
                ))
    finally:
        conn.close()
    return hits


async def search_mt_docs(platform: str, query: str, *, limit: int = 8) -> dict[str, Any]:
    """检索某平台的文档。

    Raises:
        MTDocsNotConfigured: 库未配置或文件缺失。**刻意让它冒出去**——调用方必须能
            分辨"没配好"和"文档里确实没有"，前者不该被当成事实结论。
        ValueError: 平台名非法。
    """
    if platform not in _TABLES:
        raise ValueError(f"未知平台 {platform!r}，可选：{', '.join(PLATFORMS)}")

    # sqlite 是同步阻塞的。本地文件通常毫秒级，但 12M 库上没走索引的查询能到百毫秒，
    # 且**规则要一致**——本项目已三次栽在「同步调用混进 async handler」，每次都是
    # 「这次很快、没关系」开的头。
    hits = await asyncio.to_thread(_search_sync, platform, query, limit)
    return {
        "platform": platform,
        "query": query,
        "matched_terms": literalize_query(query),
        "hits": len(hits),
        "results": [h.to_dict() for h in hits],
    }
