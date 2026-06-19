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

# __all__ 声明「from budget import *」时对外暴露哪些名字；下划线开头的辅助函数
# （如 _content_text / _signature）刻意不在此列，表明它们是模块内部实现细节。
__all__ = ["estimate_tokens", "SpinDetector"]

# 粗略经验值：英文/中文混合下约每 4 字符 ≈ 1 token（仅作防失控上限）。
# 为什么用「字符数 / 4」而不引 tiktoken：本估算只为「是否超预算、该不该收尾」做判断，
# 不是精确计费；引 tiktoken 会增加重依赖、且与具体 provider 的分词器绑定。粗估即够用，
# 还天然跨 provider 通用（任何模型都能用同一把尺子量上下文体量）。
_CHARS_PER_TOKEN = 4


def _content_text(content: Any) -> str:
    """把消息 content（str 或 content blocks 列表）规整为可计长度的文本。"""
    # 不同 provider 的 message.content 形态不一：可能是纯字符串，也可能是
    # ``[{"type": "text", "text": ...}, ...]`` 的 block 列表。这里统一抽成纯文本，
    # 只为「数字符长度」服务。（与 agent_loop._content_text 同构，但那边还要拼回复文本。）
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))  # 只取文本块；图片/工具调用等块不计长度
        return "".join(parts)
    return str(content)  # 兜底：其它类型直接 str 化再量长度


def estimate_tokens(messages: Sequence[Any]) -> int:
    """估算一组消息的累计 token 数（字符数 / 4 的粗略近似）。

    ``messages`` 中每个元素需有 ``content`` 属性（LangChain ``BaseMessage``）。
    返回值仅用于"是否超过防失控预算"的判断，不代表精确计费。
    """
    # 逐条消息抽文本、累加字符数。getattr(m, "content", "") 给没有 content 属性的
    # 元素一个安全兜底（取空串），不会因个别异常元素而抛 AttributeError。
    total_chars = sum(len(_content_text(getattr(m, "content", ""))) for m in messages)
    # 整除而非浮点：返回 int，配合「> max_tokens」的整数比较即可，无需小数精度。
    return total_chars // _CHARS_PER_TOKEN


def _signature(tool_calls: Sequence[dict[str, Any]]) -> tuple[tuple[str, str], ...]:
    """把一步的工具调用规整为可比较签名：每项 (name, 规范化 args JSON)。"""
    # 目标：把「这一步调了哪些工具、各带什么参数」压成一个可用 == 直接比较的不可变值，
    # 好让 SpinDetector 判断「这步和上步是不是一模一样」。两处归一化是关键：
    #
    # ① 每个 call → (name, json.dumps(args, sort_keys=True))：
    #    sort_keys=True 把 args 的键排序，故 {"a":1,"b":2} 与 {"b":2,"a":1} 序列化后
    #    完全相同——即「字段顺序不影响判定」，避免因 dict 键序抖动而漏判打转。
    #    ensure_ascii=False 让中文按原样进 JSON（不转 \uXXXX），可读、也不影响相等性。
    # ② 外层 sorted(...)：把同一步内「多个工具调用」也排序，故工具列表的先后顺序
    #    同样不影响签名——只要「调了同一组(工具+参数)」就视为相同。
    #
    # 返回 tuple（不可变、可哈希、可 == 比较），正好充当签名。
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
        self._repeat_limit = repeat_limit          # 连续相同达几次判打转；None=禁用
        self._last_sig: Optional[tuple[tuple[str, str], ...]] = None  # 上一步的签名
        self._count = 0                            # 当前签名「已连续出现」的次数
        # 注意：检测器是「有状态」的——它跨步累计连击数，故必须每次 run 各 new 一个
        # 实例（AgentLoop 正是在每次 run 开头新建），不可全局复用，否则计数会串台。

    def check(self, tool_calls: Sequence[dict[str, Any]]) -> bool:
        """记录本步工具调用并返回是否已判定打转。"""
        # 禁用开关：repeat_limit 为 None 时恒返回 False，等于关闭打转检测。
        if self._repeat_limit is None:
            return False
        sig = _signature(tool_calls)  # 把本步工具调用压成可比较签名（见 _signature）
        # 核心逻辑：与上一步签名相同则连击 +1；不同则「重置」为新签名、连击归 1。
        # 易误解点：是「连续」相同才累加——中间只要出现一次不同的调用，计数就清零，
        # 故它抓的是「卡在同一动作上反复横跳」，而非「整个会话里某动作出现过几次」。
        if sig == self._last_sig:
            self._count += 1
        else:
            self._last_sig = sig
            self._count = 1
        # 达到上限即判打转。这是早于 max_steps 的「逃生口」：模型陷入死胡同时及时止损，
        # 不必白白耗满全部步数。返回 True 后由 AgentLoop 负责终止并给兜底回复。
        return self._count >= self._repeat_limit
