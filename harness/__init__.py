"""Harness 核心包：把模型推理与可调用能力（工具层）解耦。

Phase 2 引入 ``harness.tools`` —— 把 ``services/`` 的能力包装成 LLM 可调用工具，
为后续 Phase 3 的 agent loop 提供"动作"层。见 docs/harness-refactor-plan.md。
"""
