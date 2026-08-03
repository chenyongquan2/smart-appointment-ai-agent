"""MT4/MT5 平台文档库配置（OnCall 值守域）。

两个 FTS 库是**别处维护的知识快照**，本仓只是使用方——故走配置路径、不进版本库
（12M 的 `mt5api.db` 塞进 git，每次更新都是一个无法增量的二进制 diff）。

未配置时**明确失败**，与 `services/knowledge_search.py` 的「知识库未接入」同一条纪律：
空结果会被模型读成"查过了、文档里没有这个码"，进而凭训练知识**编造 API 语义**——
在值守场景里，编造一个返回码的含义比如实说"查不到"危险得多。
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["MTDocsNotConfigured", "DB_FILENAMES", "resolve_db_path"]

_DIR_ENV = "ONCALL_MT_DOCS_DIR"

# 平台 → 库文件名。与参考系统 `.opencode/skills/*/references/` 下的命名一致，
# 便于直接把那两个文件拷过来用。
DB_FILENAMES = {"mt4": "mt4docs.db", "mt5": "mt5api.db"}


class MTDocsNotConfigured(RuntimeError):
    """文档库未配置或文件缺失。

    **刻意与「查无此项」区分开**：调用方（模型）必须能分辨"没配好"和"文档里确实没有"，
    否则会把配置问题当成事实结论继续推断。
    """


def resolve_db_path(platform: str) -> Path:
    """取某平台的库文件路径；未配置或缺失即抛 :class:`MTDocsNotConfigured`。"""
    if platform not in DB_FILENAMES:
        raise ValueError(f"未知平台 {platform!r}，可选：{', '.join(sorted(DB_FILENAMES))}")

    raw = os.getenv(_DIR_ENV, "").strip()
    if not raw:
        raise MTDocsNotConfigured(
            f"MT 文档库未配置：环境变量 {_DIR_ENV} 未设置。"
            "这是**配置缺失**、不是文档里查不到——请如实告知用户该能力尚未接入，"
            "不要据此推断 API 语义。"
        )

    path = Path(raw).expanduser() / DB_FILENAMES[platform]
    if not path.is_file():
        raise MTDocsNotConfigured(
            f"MT 文档库文件缺失：{path.name} 不在 {raw} 下。"
            "这是**配置问题**、不是文档里查不到。"
        )
    return path
