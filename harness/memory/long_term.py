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
        self._repo = repo      # 偏好数据来源；None 表示「不启用长期记忆」（如纯测试）
        self.top_k = top_k     # 每类偏好最多保留几条，避免提示过长稀释重点

    def build_preference_hint(self, user_id: str) -> str:
        """返回中文偏好提示补充；无偏好/异常时返回空串。"""
        # 没有 repo 或没有 user_id 就「无可读」，直接返回空串（调用方收到空串即不追加提示）。
        if self._repo is None or not user_id:
            return ""
        try:
            # prefs 形如 [{"preference_type": ..., "preference_value": ..., "confidence_score": ...}, ...]
            # 已在 repo 侧按置信度排好序（高置信在前），这里直接顺序取用。
            prefs = self._repo.get_user_preferences(user_id)
        except Exception as exc:  # noqa: BLE001 —— 长期记忆失败不应影响主流程
            # 关键设计：偏好只是「锦上添花」，读不到也得让对话照常进行。
            # 故这里「吞掉」一切异常（DB 挂了/字段缺失……），只记一条 warning 日志，
            # 然后返回空串当作「这次没有偏好」——绝不把异常往上抛、绝不拖垮主流程。
            logger.warning("读取用户偏好失败（user_id=%s）：%s", user_id, exc)
            return ""

        if not prefs:
            return ""  # 该用户暂无任何已学到的偏好

        # 按类型分组，每组取前 top_k 个偏好值。
        # 目标形态：{"technician": ["小李", "小王"], "time": ["晚上"], ...}
        grouped: dict[str, list[str]] = {}
        for p in prefs:
            ptype = p.get("preference_type", "")   # 偏好类别，如 technician/time
            pvalue = p.get("preference_value", "")  # 偏好取值，如「小李」
            if not pvalue:
                continue  # 跳过空值（脏数据保护）
            # setdefault：该类型首次出现就建空列表并返回，已存在就返回原列表——一行完成「取或建桶」。
            bucket = grouped.setdefault(ptype, [])
            if len(bucket) < self.top_k:  # 每类最多 top_k 条；因 prefs 已按置信度排序，先到的更可信
                bucket.append(str(pvalue))

        if not grouped:
            return ""  # 全是空值被过滤光了，等价于无偏好

        # 把分组渲染成一句人话提示，如「技师：小李、小王；时间：晚上」。
        parts = []
        for ptype, values in grouped.items():
            # 类型转中文标签；未知类型回退到原始 ptype，再不行用「偏好」兜底。
            label = _TYPE_LABELS.get(ptype, ptype or "偏好")
            parts.append(f"{label}：{'、'.join(values)}")
        # 措辞刻意强调「供参考、非硬性要求」：偏好是软提示，避免模型把它当成必须执行的硬约束。
        # 这段返回值最终作为 system_suffix 拼到系统提示末尾（见 AgentLoop.run）。
        return "已知该用户的历史偏好（供参考，非硬性要求）——" + "；".join(parts) + "。"
