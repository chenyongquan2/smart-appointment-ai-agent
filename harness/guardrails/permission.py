"""危险操作权限闸门（Phase 5）。

危险（``dangerous``）工具在分发前 MUST 先经一个**可注入**的权限策略判定：策略接收
（工具、入参）返回一个结构化 :class:`Decision`（放行 / 拒绝 + 理由）。被拒时不执行
handler，由 ``ToolRegistry`` 把结构化拒绝结果交回 ``AgentLoop`` 经错误回灌路径喂给模型。

策略以一个可调用对象表达：``Callable[[Tool, dict], Decision]``。未注入策略时默认放行
（:func:`allow_all`），保持既有行为不破坏现有测试与 evals（见 design.md D5）。

要点串讲：
- **策略是可调用对象**——函数/lambda 即可，无需类层级，故极易注入与替换。
- **默认 allow_all 向后兼容**——缺省不设防，行为与接入闸门前一致；要拦截须显式注入更严的策略。
- **危险工具被拒返回结构化拒绝**——不抛异常、不静默吞掉，而是回一个带理由的 :class:`Decision`，
  由 ``ToolRegistry`` 转成结构化结果走「错误回灌」路径喂回模型，让它知道「为何不让做」并自行改道。

与重试护栏（``guardrails/retry``）呼应同一条不对称哲学：**LLM 调用可重试、工具调用绝不重试**。
正因工具（尤其 ``dangerous`` 工具）一旦执行就可能产生不可逆副作用，才在「执行前」加这道权限闸门——
宁可拒于门外，也不能先做了再后悔（更不能靠重试来「补救」一个已经发生的副作用）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

# TYPE_CHECKING 在「类型检查时」为真、「运行时」为假：故 Tool 仅供类型注解用，
# 运行时不会真的 import 它。这样 guardrails 不必在运行时反向依赖 tools 模块——
# 打破潜在的循环 import（tools 用 guardrails，guardrails 又 import tools）。
if TYPE_CHECKING:  # 仅类型注解用，避免运行时反向依赖
    from harness.tools.base import Tool

# 对外只暴露这三个名字：决定类型、策略类型别名、默认策略。
__all__ = ["Decision", "PermissionPolicy", "allow_all"]


@dataclass(frozen=True)
class Decision:
    """权限判定结果：是否放行 + 拒绝理由。"""
    # frozen=True 让实例不可变（创建后改字段会报错）：决定一旦做出就是定论，不该被
    # 后续代码偷偷篡改。用 dataclass 而非裸 bool：返回「结构化」结果而非字符串/布尔，
    # 既带放行与否、又带「为什么拒」的理由，便于回灌给模型说明（结构化输出 > 字符串）。

    allow: bool       # True=放行，False=拒绝
    reason: str = ""  # 拒绝理由（放行时通常为空）；会被回灌给模型解释「为何不让做」

    # 下面两个工厂方法是「便利构造器」：让调用处用 Decision.allowed() / Decision.denied(...)
    # 语义清晰地造决定，而不必记 allow=True/False 的位置参数。
    @classmethod
    def allowed(cls) -> "Decision":
        return cls(allow=True)

    @classmethod
    def denied(cls, reason: str) -> "Decision":
        return cls(allow=False, reason=reason)


# 权限策略类型：给定（工具, 入参）返回放行/拒绝决定。
# 关键设计：策略就是「一个可调用对象」（函数/lambda/带 __call__ 的对象皆可），而非
# 一个庞大的策略类层级。好处是极轻量、易注入、易测——想换策略只需传入另一个可调用。
# 这只是个「类型别名」，给所有符合此签名的可调用一个统一名字，便于注解与阅读。
PermissionPolicy = Callable[["Tool", dict[str, Any]], Decision]


def allow_all(tool: "Tool", args: dict[str, Any]) -> Decision:
    """默认策略：放行一切（保持未配置策略时的既有行为）。"""
    # 为什么默认放行：向后兼容。Phase 5 之前没有权限闸门，若默认改成「默认拒绝」会
    # 一夜之间打挂所有现有测试与 evals。故缺省 = allow_all，行为与接入护栏前完全一致；
    # 真要拦截危险工具时，由调用方「显式注入」一个更严格的策略来覆盖它。
    # 注意它无视入参直接放行——这是「不设防」的占位策略，不是「审查后放行」。
    return Decision.allowed()
