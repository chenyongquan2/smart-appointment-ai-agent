"""OnCall 值守域的工具集。

五个工具，**全部只读**（`dangerous=False`）：日志查询、资料加载、源码定位、源码检索、
源码阅读。值守域连 clone 都没有——那是写操作，会被 `policy.py` 拒绝（见 change
`oncall-domain-code` 的 design D2）。
"""

from domains.oncall.tools.code import (
    code_search,
    locate_service_code_tool,
    read_source,
)
from domains.oncall.tools.reference import load_reference
from domains.oncall.tools.vlog import vlog_query

TOOLS = (
    vlog_query,
    load_reference,
    locate_service_code_tool,
    code_search,
    read_source,
)

__all__ = [
    "TOOLS",
    "vlog_query",
    "load_reference",
    "locate_service_code_tool",
    "code_search",
    "read_source",
]
