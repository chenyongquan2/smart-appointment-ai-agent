"""循环预算护栏：token 近似估算 + 打转检测（Phase 5）。

两道早于 ``max_steps`` 的逃生口，均为防失控上限、不要求精确计费：

- :func:`estimate_tokens`：基于消息体量的粗略 token 估算（字符数 / 4），用于在
  ``AgentLoop`` 每步前判断累计上下文是否超过配置预算。
- :class:`SpinDetector`：检测"原地打转"——连续若干步出现完全相同的工具调用
  （相同名称与相同参数）即判定循环卡死。

设计要点（见 design.md D3/D4）：估算无需引入 tiktoken 等依赖、跨 provider 适用；
打转签名由 ``(name, 规范化 args)`` 构成，对参数排序后比较，故字段顺序不影响判定。
"""

from __future__ import annotations

import json
from typing import Any, Optional, Sequence

__all__ = ["estimate_tokens", "SpinDetector"]

# 粗略经验值：英文/中文混合下约每 4 字符 ≈ 1 token（仅作防失控上限）。
_CHARS_PER_TOKEN = 4


def _content_text(content: Any) -> str:
    """把消息 content（str 或 content blocks 列表）规整为可计长度的文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
        return "".join(parts)
    return str(content)


def estimate_tokens(messages: Sequence[Any]) -> int:
    """估算一组消息的累计 token 数（字符数 / 4 的粗略近似）。

    ``messages`` 中每个元素需有 ``content`` 属性（LangChain ``BaseMessage``）。
    返回值仅用于"是否超过防失控预算"的判断，不代表精确计费。
    """
    total_chars = sum(len(_content_text(getattr(m, "content", ""))) for m in messages)
    return total_chars // _CHARS_PER_TOKEN


def _signature(tool_calls: Sequence[dict[str, Any]]) -> tuple[tuple[str, str], ...]:
    """把一步的工具调用规整为可比较签名：每项 (name, 规范化 args JSON)。"""
    return tuple(
        sorted(
            (
                str(call.get("name", "")),
                json.dumps(call.get("args") or {}, sort_keys=True, ensure_ascii=False),
            )
            for call in tool_calls
        )
    )


class SpinDetector:
    """检测连续相同的工具调用（打转）。

    每步把该步的工具调用喂给 :meth:`check`；当同一签名连续出现达到 ``repeat_limit``
    次时返回 ``True``，调用方据此提前终止循环。``repeat_limit`` 为 ``None`` 时禁用检测
    （:meth:`check` 恒返回 ``False``）。
    """

    def __init__(self, repeat_limit: Optional[int] = 3) -> None:
        self._repeat_limit = repeat_limit
        self._last_sig: Optional[tuple[tuple[str, str], ...]] = None
        self._count = 0

    def check(self, tool_calls: Sequence[dict[str, Any]]) -> bool:
        """记录本步工具调用并返回是否已判定打转。"""
        if self._repeat_limit is None:
            return False
        sig = _signature(tool_calls)
        if sig == self._last_sig:
            self._count += 1
        else:
            self._last_sig = sig
            self._count = 1
        return self._count >= self._repeat_limit
