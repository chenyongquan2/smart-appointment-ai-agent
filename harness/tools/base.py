"""工具抽象基类。

每个工具是 ``services/`` 的薄封装，声明四要素：
``name`` / ``description`` / ``args_schema`` / ``handler``。
handler 统一为 async（对齐 Phase 3 的 async agent loop，也让工具能直接 await 外部
I/O——如知识库检索端口），签名为 ``async def handler(args: BaseModel) -> Any``。

工具 MUST NOT 重写业务逻辑——仅把已校验的参数转交给对应 service 方法。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Final, Optional

from pydantic import BaseModel

# 声明「本工具不受超时约束」的取值。用于 handler 内部本就是长任务的编排型工具——
# 典型是 delegate：它的 handler 跑的是一整个子 AgentLoop（多步 LLM 调用），
# 与一次本地 DB 查询共用同一个上限必然误杀其一（见 change: feishu-channel-integration D3）。
NO_TIMEOUT: Final[float] = math.inf


# frozen=True：实例创建后字段只读（不可变）。工具是「声明式配置」，注册后不该被改，
# 不可变也让它能安全地在多处共享（如 subset 切片时复用同一 Tool 实例）。
@dataclass(frozen=True)
class Tool:
    """一个可被 LLM 调用的工具。

    Tool 的「四要素」就是下面前四个字段：name（叫什么）、description（什么时候用，
    给模型看）、args_schema（参数长什么样，用于校验）、handler（实际干活的函数）。
    第五个 dangerous 是给权限闸门用的标记。

    Attributes:
        name: 唯一工具名（snake_case），用于注册与分发。
        description: 面向模型的说明书——决定模型何时调用本工具。
        args_schema: 入参的 Pydantic v2 模型；分发前用它校验原始参数。
        handler: ``async def handler(args: args_schema) -> Any``，
            接收已校验的 args 模型实例，内部调用 services/。
        dangerous: 是否为有副作用的危险操作（如写库的 ``create_appointment``）。
            危险工具在分发前须经权限闸门判定（见 ``harness/guardrails/permission``）；
            只读查询工具保持默认 ``False``。
        timeout: 本工具单次调用的超时秒数。``None``（默认）= 采用运行时的全局缺省；
            具体数值 = 覆盖全局缺省；``NO_TIMEOUT`` = 豁免超时。

    超时的适用边界（重要，写工具时必读）：
        超时依赖 ``asyncio`` 的取消机制，**只能中断在 await 点让出控制权的 handler**。
        若 handler 内部执行的是同步阻塞调用（同步 SQLite / FAISS / 子进程等），到点也
        取消不掉，它会一直占着事件循环直到自己返回——此时即使声明了 ``timeout`` 也
        **没有**超时保护。需要真实超时的同步工具 MUST 自行把阻塞调用下沉到线程池
        （如 ``asyncio.to_thread``），否则 ``timeout`` 只是一句空声明。
    """

    # ── 四要素 ──────────────────────────────────────────────────────────
    name: str                                              # 例："search_knowledge"
    description: str                                       # 喂给 LLM 的「说明书」，措辞直接影响模型调不调它
    args_schema: type[BaseModel]                           # 注意是「类」本身（type[...]），不是实例；run() 里才实例化
    handler: Callable[[BaseModel], Awaitable[Any]]         # 收「已校验的 args 实例」，返回 awaitable（统一 async）
    dangerous: bool = False                                # 默认只读安全；写库类工具显式置 True，触发权限判定
    timeout: Optional[float] = None                        # None=取全局缺省；数值=覆盖；NO_TIMEOUT=豁免（见类 docstring 的适用边界）

    async def run(self, raw_args: dict[str, Any]) -> Any:
        """校验原始参数并执行 handler。"""
        # ① 校验：raw_args 是 LLM 给的「原始字典」（如 {"query": "营业时间", "top_k": 3}），
        #    形态可能不对（缺字段/类型错/越界）。用 args_schema 实例化做一次 Pydantic 校验，
        #    不合法会在此抛 ValidationError——把脏数据挡在 handler 之外。
        validated = self.args_schema(**raw_args)
        # ② 执行：handler 拿到的是「已校验的强类型 model 实例」（而非原始字典），
        #    可放心用 validated.query 这类属性访问，无需自己再校验。
        return await self.handler(validated)
