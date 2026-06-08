"""长期记忆：跨会话读取用户偏好（Phase 4：状态与记忆）。

薄封装既有 ``UserBehaviorRepository.get_user_preferences``，把高置信度偏好组装成
一段中文提示补充，供 ``AgentLoop`` 的系统提示使用。**不重写**偏好业务逻辑，
仅做读取与组装；读取失败或无偏好返回空串，不影响主流程。

详见 OpenSpec change phase-4-state-memory design.md D4。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 偏好类型 → 中文标签（与 db 模型 preference_type 取值对应）。
_TYPE_LABELS = {
    "technician": "技师",
    "time": "时间",
    "service": "服务项目",
    "duration": "服务时长",
}


class LongTermMemory:
    """读取用户偏好并组装为系统提示补充。

    Args:
        repo: 提供 ``get_user_preferences(user_id) -> list[dict]`` 的对象
            （既有 ``UserBehaviorRepository`` 或鸭子类型等价物）。可为 ``None``。
        top_k: 每种偏好最多取多少条（按 confidence_score 已在 repo 侧排序）。
    """

    def __init__(self, repo=None, top_k: int = 3) -> None:
        self._repo = repo
        self.top_k = top_k

    def build_preference_hint(self, user_id: str) -> str:
        """返回中文偏好提示补充；无偏好/异常时返回空串。"""
        if self._repo is None or not user_id:
            return ""
        try:
            prefs = self._repo.get_user_preferences(user_id)
        except Exception as exc:  # noqa: BLE001 —— 长期记忆失败不应影响主流程
            logger.warning("读取用户偏好失败（user_id=%s）：%s", user_id, exc)
            return ""

        if not prefs:
            return ""

        # 按类型分组，每组取前 top_k 个偏好值。
        grouped: dict[str, list[str]] = {}
        for p in prefs:
            ptype = p.get("preference_type", "")
            pvalue = p.get("preference_value", "")
            if not pvalue:
                continue
            bucket = grouped.setdefault(ptype, [])
            if len(bucket) < self.top_k:
                bucket.append(str(pvalue))

        if not grouped:
            return ""

        parts = []
        for ptype, values in grouped.items():
            label = _TYPE_LABELS.get(ptype, ptype or "偏好")
            parts.append(f"{label}：{'、'.join(values)}")
        return "已知该用户的历史偏好（供参考，非硬性要求）——" + "；".join(parts) + "。"
