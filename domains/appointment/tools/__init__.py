"""预约域的工具集。

每个工具一个文件，导出一个 `Tool` 实例。工具是 `services/` 的薄封装——只做
「参数校验 + 转交」，MUST NOT 重写业务逻辑（见 openspec/specs/tool-layer）。
"""

from domains.appointment.tools.appointment import create_appointment
from domains.appointment.tools.availability import check_availability
from domains.appointment.tools.knowledge import search_knowledge
from domains.appointment.tools.preference import get_user_preferences
from domains.appointment.tools.technician import find_technician

# 顺序不影响分发（按名查找），但会影响导出给 LLM 的 schema 列举顺序。
# 保持与领域包化之前 build_default_registry 的注册顺序一致，避免提示词无谓变动。
TOOLS = (
    search_knowledge,
    find_technician,
    check_availability,
    create_appointment,   # 唯一写库的危险工具（dangerous=True），分发时过权限闸门
    get_user_preferences,
)

__all__ = [
    "TOOLS",
    "search_knowledge",
    "find_technician",
    "check_availability",
    "create_appointment",
    "get_user_preferences",
]
