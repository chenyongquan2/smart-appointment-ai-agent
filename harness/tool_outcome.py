"""工具派发结果的**文案契约**——单一真相源（change ``fix-trace-triage-blindspots``）。

## 为什么需要这个模块

工具超时/失败时，``AgentLoop._dispatch`` 把异常吞成一句话当正常工具结果回灌给模型；
而 ``harness/observability/trace_signals.py`` 要靠**认出这句话**来判定失控信号。也就是
说这句文案是两个模块之间的**隐式契约**。

它出过一次事故：超时支当初刻意从通用 ``except Exception`` 里拆出来（为给模型一句能据以
决策的明确说明——是"太慢被掐断"而非"参数错"），但 ``trace_signals`` 只认"工具执行**失败**"
这个前缀，于是"工具执行**超时**"从此静默不再命中信号。后果是真实群聊里"连吃三次 60 秒
超时、白等 3 分钟"这个坏 case 在 triage 里报 0 个候选——**最常见的真实故障恰好不可见**。

## 为什么导出函数而不只是前缀常量

只共享前缀的话，调用方仍持有 ``f"{PREFIX}（{name}）：…"`` 的拼装，下一个人改个括号或
分隔符照样能悄悄破坏 ``startswith``。把**整句的生成权**收进这里，调用方就没有可漂移的
余地——这才是对根因下药，而不是把匹配串改对了完事。

## 为什么放 ``harness/`` 顶层而不是 runtime/ 或 observability/ 里

- 放 ``harness/runtime/`` 下会 **import 期成环**：``harness/runtime/__init__.py`` 导入
  ``AgentLoop``，而 ``AgentLoop`` 导入 ``harness.observability.tracer``；若 ``trace_signals``
  反向导入 ``harness.runtime.*`` 即构成循环，还会把轻量 exporter 拖进整个 langchain 依赖树。
- 放 ``harness/observability/`` 里方向上可行，但等于让可观测层拥有**运行时喂给模型看的
  文案**——职责错位，下一个人改文案时不会想到去 observability 找。
- ``harness/__init__.py`` 只有 docstring、零 import，故顶层小模块是干净落点。

本模块 MUST 保持零重依赖（不 import langchain / observability / runtime），否则成环风险
会被搬回来。
"""

from __future__ import annotations

from typing import Union

__all__ = [
    "TOOL_TIMEOUT_PREFIX",
    "TOOL_FAILURE_PREFIX",
    "tool_timeout_message",
    "tool_failure_message",
]

# 两句文案的前缀：``trace_signals`` 用它们做 startswith 判定，故 MUST 与下面两个
# 格式化函数产出的开头逐字一致。改文案请改函数，前缀常量随之调整——两者一起改，
# 测试（test_tool_outcome.py）会核对它们同源。
TOOL_TIMEOUT_PREFIX = "工具执行超时"
TOOL_FAILURE_PREFIX = "工具执行失败"


def tool_timeout_message(name: str, timeout: Union[int, float, None]) -> str:
    """工具因超时被中断时回灌给模型的说明。

    刻意与 ``tool_failure_message`` 分成两句：让模型知道是"太慢被掐断"而非"参数错/
    服务报错"，下一轮可换更窄的查询（而不是加宽）。
    """
    return f"{TOOL_TIMEOUT_PREFIX}（{name}）：超过 {timeout} 秒未返回，已中断且不会重试。"


def tool_failure_message(name: str, exc: object) -> str:
    """工具抛异常时回灌给模型的说明（异常被吞成正常工具结果，不崩循环）。"""
    return f"{TOOL_FAILURE_PREFIX}（{name}）：{exc}"
