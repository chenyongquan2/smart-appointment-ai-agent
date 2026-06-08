"""harness 护栏层（Phase 5）。

围绕 LLM 调用与工具分发的可靠性外壳，使 harness 在生产环境可信：

- ``retry``：LLM 调用的超时 + 指数退避重试（``guarded_invoke`` / ``GuardrailExhausted``）。
- ``budget``：循环 token 预算近似估算（``estimate_tokens``）与打转检测（``SpinDetector``）。
- ``permission``：危险工具操作的可注入权限闸门（``Decision`` / ``allow_all``）。

护栏均为 harness 内的薄封装，MUST NOT 触碰 ``services/`` / ``db/`` /
``config/model_provider`` / RAG。
"""

from harness.guardrails.budget import SpinDetector, estimate_tokens
from harness.guardrails.permission import Decision, allow_all
from harness.guardrails.retry import GuardrailExhausted, guarded_invoke

__all__ = [
    "guarded_invoke",
    "GuardrailExhausted",
    "estimate_tokens",
    "SpinDetector",
    "Decision",
    "allow_all",
]
