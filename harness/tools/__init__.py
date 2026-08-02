"""harness.tools：工具层的**域无关**部分。

``Tool`` 定义结构 + ``ToolRegistry`` 注册/分发/导出 schema。具体工具**不在这里**——
它们随领域包走（见 ``domains/``），因为「有哪些工具」是域的属性，不是运行时的属性。
"""

from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry

__all__ = ["Tool", "ToolRegistry"]
