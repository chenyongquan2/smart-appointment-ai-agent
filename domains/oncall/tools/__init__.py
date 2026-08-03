"""OnCall 值守域的工具集。

两个都是**只读**工具（`dangerous=False`）——值守域的只读红线由 `policy.py` 硬 enforce，
不靠这里的自觉。
"""

from domains.oncall.tools.reference import load_reference
from domains.oncall.tools.vlog import vlog_query

TOOLS = (vlog_query, load_reference)

__all__ = ["TOOLS", "vlog_query", "load_reference"]
