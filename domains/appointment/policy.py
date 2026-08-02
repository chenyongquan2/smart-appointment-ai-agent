"""预约域的权限策略。

**当前策略 = 放行全部**，与领域包化之前的实际行为完全一致——此前 `api/chat_handler.py`
根本没给 `ToolRegistry` 传 policy，走的就是 `allow_all` 默认。这里只是把**隐式的行为
写成显式声明**，判定结果一字不变。

那为什么要专门起个文件？因为权限闸门虽然早就实现了，却**从未被接进生产路径**——一条
从未被验证过的接线等于没有。oncall 域（第 3 期）的「全工具只读」红线要靠它硬 enforce；
若到那时才发现分发根本不查策略，红线就只是纸面约定。故在纯搬迁这一期把管道通了，
并留测试守着。

要收紧本域时（如要求 create_appointment 前置人工确认），改这里即可，不动运行时。
"""

from __future__ import annotations

from harness.guardrails.permission import allow_all

__all__ = ["POLICY"]

POLICY = allow_all
