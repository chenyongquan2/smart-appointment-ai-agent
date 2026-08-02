"""VictoriaLogs 凭据与超时配置（OnCall 值守域）。

**凭据只在这里与 `services/vlog.py` 出现，绝不进 LLM 上下文**——日志查询工具的入参
schema 里没有任何地址/用户名/密码字段，模型既看不见也传不了（见 change
`oncall-domain-vlog` 的 design D6）。

超时解析沿用 `config/model_provider.py` 的 `resolve_embedding_timeout` 口径：
显式参数 > 环境变量 > 缺省，且**缺省必须是显式的秒级数值**，不能落到 HTTP 客户端的
默认值——那是 `guardrails` 的「外部调用超时与非阻塞」里写死的约束。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = [
    "VLogCredentials",
    "DEFAULT_VLOG_TIMEOUT",
    "load_vlog_credentials",
    "resolve_vlog_timeout",
]

# 日志查询确实比嵌入慢（大时间窗全表扫），故缺省比 embedding 的 20s 宽。
# 但**上限必须显式**：不设的话 httpx 默认 5s 会误杀正常查询，而某些客户端默认是无上限。
DEFAULT_VLOG_TIMEOUT = 60.0

_URL_ENV = "VM_LOGS_URL"
_USER_ENV = "VM_LOGS_USER"
_PASSWORD_ENV = "VM_LOGS_PASSWORD"
_TIMEOUT_ENV = "VM_LOGS_TIMEOUT_SECONDS"


@dataclass(frozen=True)
class VLogCredentials:
    """VictoriaLogs 连接凭据。frozen：读出来就不该被改。"""

    url: str
    user: str
    password: str


class VLogNotConfigured(RuntimeError):
    """凭据未配置。

    与 `services/knowledge_search.py` 的「知识库未接入」同一思路：**明确失败**，
    不返回空结果——空结果会被模型读成"查了、没有日志"，进而给出错误结论。
    """


def load_vlog_credentials() -> VLogCredentials:
    """从环境变量读取凭据；缺任一项即明确失败。"""
    url = os.getenv(_URL_ENV, "").strip()
    user = os.getenv(_USER_ENV, "").strip()
    password = os.getenv(_PASSWORD_ENV, "").strip()
    missing = [k for k, v in ((_URL_ENV, url), (_USER_ENV, user), (_PASSWORD_ENV, password)) if not v]
    if missing:
        raise VLogNotConfigured(
            f"日志查询凭据未配置，缺少：{', '.join(missing)}。"
            "请在 .env 中补齐后重试（凭据只在服务层使用，不会进入模型上下文）。"
        )
    return VLogCredentials(url=url, user=user, password=password)


def resolve_vlog_timeout(explicit: float | None = None) -> float:
    """解析超时秒数：显式参数 > ``VM_LOGS_TIMEOUT_SECONDS`` > ``DEFAULT_VLOG_TIMEOUT``。

    环境变量写错（非数字/空）时回落到缺省而非抛错——配置手滑不该让服务起不来。
    """
    if explicit is not None:
        return float(explicit)
    raw = os.getenv(_TIMEOUT_ENV)
    if not raw:
        return DEFAULT_VLOG_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_VLOG_TIMEOUT
