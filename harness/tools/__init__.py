"""harness.tools：把 services/ 能力暴露为 LLM 可调用工具。

每个工具一个文件，导出一个 ``Tool`` 实例；``ToolRegistry`` 负责注册/分发/导出 schema。
"""

from harness.tools.appointment import create_appointment
from harness.tools.availability import check_availability
from harness.tools.base import Tool
from harness.tools.knowledge import search_knowledge
from harness.tools.preference import get_user_preferences
from harness.tools.registry import ToolRegistry, build_default_registry
from harness.tools.technician import find_technician

__all__ = [
    "Tool",
    "ToolRegistry",
    "build_default_registry",
    "search_knowledge",
    "find_technician",
    "check_availability",
    "create_appointment",
    "get_user_preferences",
]
