"""harness 记忆层（Phase 4：状态与记忆）。

分层记忆：
- ``ShortTermMemory``：最近 N 轮对话窗口，注入 LLM 上下文。
- ``LongTermMemory``：跨会话读取用户偏好（薄封装既有 UserBehaviorRepository）。
- ``SummaryMemory`` / ``NoOpSummary``：摘要层接口与占位实现（本 Phase 留 stub）。
"""

from harness.memory.short_term import ShortTermMemory
from harness.memory.long_term import LongTermMemory
from harness.memory.summary import SummaryMemory, NoOpSummary

__all__ = ["ShortTermMemory", "LongTermMemory", "SummaryMemory", "NoOpSummary"]
