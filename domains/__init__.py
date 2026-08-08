"""领域包：把「域」收敛成一个可装载的包。

**换域 = 换五样东西**：工具集 + 子 Agent 集 + 系统提示 + 权限策略 + 评估数据与标注口径。
运行时（TAO 循环、记忆、护栏、Tracer、评估运行器）**一行不动**——这正是本模块存在的
全部理由，也是它的验收标准。

判断某段代码该放哪，只问一句话：**换成另一个域还成立吗？**

- 成立 → 域无关，留 ``harness/`` 或 ``evals/``（如 ``ToolRegistry``、``build_system_prompt``
  的拼接逻辑、多采样 CI、门禁）
- 不成立 → 进领域包（如"你是一家按摩门店的智能助手"、``create_appointment`` 工具）

见 change ``domain-packages`` 与 ``docs/oncall-bot-roadmap.md`` 第 2 期。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from domains.eval_profile import EvalProfile

if TYPE_CHECKING:  # 仅类型注解，避免 import 期拉起 harness 的重型依赖
    from harness.guardrails.permission import PermissionPolicy
    from harness.subagents.base import SubAgent
    from harness.tools.base import Tool

__all__ = [
    "Domain",
    "EvalProfile",
    "load_domain",
    "available_domains",
    "build_tool_registry",
    "build_subagent_registry",
    "build_main_registry",
    "DEFAULT_DOMAIN",
    "DOMAIN_ENV_VAR",
]

DOMAIN_ENV_VAR = "AGENT_DOMAIN"
DEFAULT_DOMAIN = "appointment"


# frozen：域是一份**声明**，不是一组行为——它没有需要子类覆写的方法，故用 dataclass
# 而非抽象基类（与项目里的 Tool / SubAgent 一致）。frozen 还保证装载后没人能偷偷往里
# 塞工具——「这个部署有哪些能力」必须在装载那一刻就定死。
@dataclass(frozen=True)
class Domain:
    """一个领域包声明的全部内容。

    Attributes:
        name: 域名（即 ``AGENT_DOMAIN`` 的取值）。
        tools: 本域的工具集。**刻意是 tuple[Tool] 而不是建好的 ToolRegistry**——
            registry 的装配方式因场景而异（主 registry 只含 delegate、子 Agent 各持
            工具子集、评估要独立 exporter 沙盒），域只负责声明「我有哪些工具」，
            怎么装是运行时的事。域交出 registry 就越界了。
        subagents: 本域的子 Agent 集（同理，是声明而非 registry）。
        system_prompt: 本域的人设、职责边界与红线文本。会由
            ``harness.runtime.system_prompt.build_system_prompt`` 与工具说明书拼接。
        policy: 本域的权限策略，接入 ``ToolRegistry`` 的分发闸门。
        evals_dir: 本域评估数据（``cases.jsonl`` / ``baseline.json``）所在目录。
            **只有数据随域走，评估机制留在 evals/**（多采样 CI、门禁、triage 等域无关）。
        eval_profile: 本域的评估**标注口径**（标签白名单 / 槽位键映射 / 门禁指标集）。
            与 ``evals_dir`` 同属第五样东西：光有数据目录不够——评估机制要读一份用例，
            就得先知道「本域的标签叫什么、哪些入参算槽位、本域实际能守哪些指标」，
            而这三件事换个域就不成立。见 ``domains/eval_profile.py``。
    """

    name: str
    tools: tuple["Tool", ...]
    subagents: tuple["SubAgent", ...]
    system_prompt: str
    policy: "PermissionPolicy"
    evals_dir: Path
    eval_profile: "EvalProfile"


def _load_oncall() -> Domain:
    from domains.oncall import build_domain

    return build_domain()


def _load_appointment() -> Domain:
    # 函数内 import：装 A 域不该连带拉起 B 域的重型依赖。这在第 3 期尤其要紧——
    # oncall 域会拖着 VictoriaLogs 客户端、git worktree 之类的东西。
    from domains.appointment import build_domain

    return build_domain()


# 显式注册表，不做目录扫描 / entry_points 自动发现。本项目一共 2 个域，动态发现换来的是：
# 「装了哪个域」不可静态推断、import 副作用时机不定、打错域名时从「明确列出可选值」
# 退化成「什么都没发生」。3 行字典，一眼看得出全集。
_DOMAINS: dict[str, Callable[[], Domain]] = {
    "appointment": _load_appointment,
    "oncall": _load_oncall,
}


def available_domains() -> list[str]:
    """全部已注册的域名（供报错信息与测试列举）。"""
    return sorted(_DOMAINS)


def load_domain(name: str | None = None) -> Domain:
    """装载领域包。

    Args:
        name: 域名；``None`` 时读环境变量 ``AGENT_DOMAIN``，仍未设置则用
            ``appointment``。缺省值保证**零配置即行为不变**：不设环境变量的部署
            （含全部测试与 CI）自动装预约域。

    Raises:
        ValueError: 域名未注册。**刻意不静默回落到缺省域**——回落会让配置写错表现为
            「跑起来了但装错了域」，比启动失败危险得多（想想 oncall 部署因为一个拼写
            错误装成了预约域：它会拿着按摩人设去回答线上故障）。
    """
    resolved = name or os.getenv(DOMAIN_ENV_VAR) or DEFAULT_DOMAIN
    factory = _DOMAINS.get(resolved)
    if factory is None:
        raise ValueError(
            f"未知领域 '{resolved}'。可选：{', '.join(available_domains())}。"
            f"（域名来自参数或环境变量 {DOMAIN_ENV_VAR}）"
        )
    return factory()


# ── 装配辅助 ───────────────────────────────────────────────────────────────
# Domain 只**声明**内容、不交出建好的 registry（见 Domain.tools 的说明）。但「把声明
# 装进 registry」这段循环在各组装点是一样的，重复三遍不如收在这里。注意它们是**函数**
# 而非 Domain 的方法——保持 Domain 是纯数据，也让调用方能自由地只装一部分（如主
# registry 只放 delegate）。


def build_tool_registry(domain: Domain):
    """把域声明的工具装进一个 ``ToolRegistry``，并接上本域的权限策略。

    接 policy 这件事看着不起眼，却是本设计的要点之一：权限闸门此前从未被接进生产路径
    （实际走 ``allow_all`` 默认）。一条从未验证过的接线等于没有——oncall 域的只读红线
    要靠它硬 enforce。
    """
    from harness.tools.registry import ToolRegistry

    registry = ToolRegistry(permission=domain.policy)
    for tool in domain.tools:
        registry.register(tool)
    return registry


def build_subagent_registry(domain: Domain):
    """把域声明的子 Agent 装进一个 ``SubAgentRegistry``。"""
    from harness.subagents.registry import SubAgentRegistry

    registry = SubAgentRegistry()
    for agent in domain.subagents:
        registry.register(agent)
    return registry

def build_main_registry(domain: Domain, delegate_factory=None):
    """按域的**结构**决定主 Agent 的工具面，而不是写死一种形状。

    两种形状，取决于域声明了子 Agent 没有：

    - **有子 Agent**（预约域）：主 registry 只放 ``delegate``，主 Agent 的唯一动作是
      「派给哪个专员」，领域工具藏在各子 Agent 的工具子集里。
    - **无子 Agent**（值守域）：主 registry **直接放域的全部工具**，主 Agent 自己调。

    为什么必须支持第二种：值守的主动作（查日志 → 下钻 → 定位）是一条连贯的推理链，
    下钻要用到上一步命中日志里的 pod_ip / traceId，拆成子 Agent 反而要靠汇总文本传递
    中间态、必丢细节。**强行给它包一个「持有全部工具」的子 Agent 是纯开销**——多一层
    LLM 循环、多一次上下文拷贝，换不来任何隔离收益。

    这个分支判的是 ``len(domain.subagents)``（结构属性），**不是域名**——运行时依然
    对「自己跑在哪个域」无知，见 domain-packages 的「运行时对域无知」需求。

    发现于 change ``oncall-domain-vlog`` 的冒烟：此前这段装配写死在 ``api/chat_handler``
    里，装上无子 Agent 的域会得到一个「只有 delegate、却无处可派」的主 Agent——
    域的工具够不着，且不报错。
    """
    from harness.tools.registry import ToolRegistry

    if not domain.subagents:
        return build_tool_registry(domain)

    registry = ToolRegistry(permission=domain.policy)
    registry.register(delegate_factory())
    return registry
