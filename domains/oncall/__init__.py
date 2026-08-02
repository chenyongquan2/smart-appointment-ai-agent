"""OnCall 值守域领域包 —— 查日志、定位线上问题。

按 change `domain-packages` 定下的五槽位填。与预约域的差别值得记一笔：

| 槽位 | 预约域 | 值守域 |
|---|---|---|
| tools | 5 个（含 1 个写库） | 2 个，**全只读** |
| subagents | 3 个专员 | **空**（见 subagents/__init__.py 的理由） |
| prompt | 门店助手人设 | 值守人设 + 只读红线 + 排查分诊表 |
| policy | allow_all | **拒绝一切 dangerous 工具** |
| evals | 51 条用例 | 空（第 4 期填） |

本域是「换域 = 换五样东西、运行时一行不动」这条判断的第一次实检。
"""

from __future__ import annotations

from pathlib import Path

from domains import Domain

__all__ = ["build_domain"]

_EVALS_DIR = Path(__file__).parent / "evals"


def build_domain() -> Domain:
    """组装值守域。由 `domains.load_domain()` 调用。"""
    from domains.oncall.policy import POLICY
    from domains.oncall.prompt import SYSTEM_PROMPT
    from domains.oncall.subagents import SUBAGENTS
    from domains.oncall.tools import TOOLS

    return Domain(
        name="oncall",
        tools=TOOLS,
        subagents=SUBAGENTS,
        system_prompt=SYSTEM_PROMPT,
        policy=POLICY,
        evals_dir=_EVALS_DIR,
    )
