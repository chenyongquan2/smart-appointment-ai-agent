"""OnCall 值守域工具的入参 schema。

每个 `Field(description=...)` 都会进 `model_json_schema()`——**那就是写给模型的提示词**，
一处定义、校验与说明两处生效（沿用预约域 schemas 的同一范式）。
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class ReferenceName(str, Enum):
    """可加载的排查资料。

    **刻意用枚举而非自由路径**：自由路径等于给模型一个任意文件读取能力，是权限漏洞。
    新增资料时在这里加一项，并同步 `prompt.py` 的分诊表（见 change oncall-domain-vlog）。
    """

    OCS_SERVICE_PROFILES = "ocs-service-profiles"
    MT_RETURNCODE = "mt-returncode"
    OCS4_RETURNCODE = "ocs4-returncode"
    OCS5_RETURNCODE = "ocs5-returncode"


class VlogQueryArgs(BaseModel):
    """vlog_query 入参。三种给法恰好给一个。"""

    term: Optional[list[str]] = Field(
        default=None,
        description=(
            "关键词/traceId/报错片段，可给多个。多个词会自动拼成引号精确 AND（走倒排索引）。"
            "用户甩来的一长串裸字符串默认按 traceId 处理。与 logsql、url 三选一。"
        ),
    )
    logsql: Optional[str] = Field(
        default=None,
        description=(
            "原始 LogsQL，用于精确过滤与下钻（如 kubernetes.pod_ip:\"10.1.2.3\"）。"
            "与 term、url 三选一。"
        ),
    )
    url: Optional[str] = Field(
        default=None,
        description=(
            "用户粘贴的 vmui 浏览器链接。参数藏在 fragment 里，本工具会自动解析——"
            "不要自己肉眼拆解链接。与 term、logsql 三选一。"
        ),
    )
    env: Optional[str] = Field(
        default=None,
        description=(
            "环境：prod / uat / dev / stg（prd 是 prod 的别名）。"
            "不给则并发探查全部环境——已知环境时务必给上，这是收窄查询最有效的手段之一。"
        ),
    )
    window: str = Field(
        default="6h",
        description=(
            "相对时间窗（如 30m / 6h / 2d），从现在往回看。**时间窗是查询性能的头号杠杆**，"
            "能窄就窄。照告警排查时反而要放宽——见 start 参数的说明。"
        ),
    )
    start: Optional[str] = Field(
        default=None,
        description=(
            "绝对起始时刻。给了它即进入精确窗模式（直接查询，用于下钻）。\n"
            "⚠ 时区坑（务必读）：告警时间通常是**北京时间**，日志 _time 显示的也是北京时间，"
            "两者直接对齐、不要换算；但本参数按 **UTC**（后端用 UTC），传绝对时刻要把北京"
            "时间减 8 小时。**更稳的做法是别用绝对窗、改用相对的 window**，避开换算。\n"
            "⚠ 告警晚于事件（检测延迟常数十秒到数分钟）：窗口要往告警时刻**之前**放宽至少"
            "10~30 分钟，绝不只查告警那一分钟——真实事故：告警 09:31、事件在 09:30:38，"
            "只卡 1 分钟窗就漏掉了，误判成『延迟告警、无需处理』。"
        ),
    )
    end: Optional[str] = Field(default=None, description="绝对结束时刻（同样按 UTC）。")
    limit: int = Field(
        default=20,
        ge=1,
        le=200,
        description=(
            "单个环境返回的最大条数。⚠ 这是**样本上限**：返回结果里 hits 是总命中数、"
            "returned 才是实际返回条数。命中量大时你拿到的只是样本，"
            "**不要在样本里筛第二个条件然后判定『没有』**——要把条件下推进查询重查。"
        ),
    )
    fields: Optional[list[str]] = Field(
        default=None,
        description=(
            "只取这些字段。不给则返回全字段对象（_time / _msg / kubernetes.pod_ip / "
            "kubernetes.pod_name 等），这些字段是下钻的抓手，通常不要限制。"
        ),
    )

    @model_validator(mode="after")
    def _exactly_one_query_form(self) -> "VlogQueryArgs":
        given = [name for name, v in (("term", self.term), ("logsql", self.logsql), ("url", self.url)) if v]
        if len(given) != 1:
            raise ValueError(
                f"term / logsql / url 必须恰好提供一个，当前提供了 {len(given)} 个"
                f"（{', '.join(given) if given else '无'}）。"
            )
        return self


class LoadReferenceArgs(BaseModel):
    """load_reference 入参。"""

    name: ReferenceName = Field(
        description=(
            "要加载的排查资料名。可选：ocs-service-profiles（服务档案：环境清单、"
            "定位字段、日志格式、根因线索）、mt-returncode（MT4/MT5 平台原生返回码）、"
            "ocs4-returncode（OCS4 业务层错误码，66xxx 段）、ocs5-returncode"
            "（OCS5 统一 result_code）。何时该读哪份见系统提示里的分诊表。"
        ),
    )


# --------------------------------------------------------------------------- #
# 源码定位与只读检索（切片 2）
# --------------------------------------------------------------------------- #
_ENV_DESC = (
    "环境：dev / uat / stg / prd。⚠ 与日志查询相反——**日志侧写 prod、代码侧写 prd**；"
    "本工具两种都收、内部归一，不必纠结。"
)


class LocateServiceCodeArgs(BaseModel):
    """locate_service_code 入参。"""

    service: str = Field(description="服务名（对应 repos/ 下的仓库目录名）。")
    env: str = Field(description=_ENV_DESC)
    sync: bool = Field(
        default=True,
        description="是否先同步到分支最新。缺省 True，且短时间内重复调用会自动跳过同步。",
    )


class CodeSearchArgs(BaseModel):
    """code_search 入参。路径无从指定——检索范围恒为整个已定位工作区。"""

    service: str = Field(description="服务名。")
    env: str = Field(description=_ENV_DESC)
    pattern: str = Field(
        description=(
            "正则表达式。找错误码/异常/方法名时直接给字面量即可（如 `66302`、"
            "`throw new BizException`）。"
        ),
    )
    glob: str = Field(
        default="*",
        description=(
            "文件名匹配（如 `*.java`、`*.cpp`）。缺省搜全部。"
            "命中太多时优先用它收窄，比放宽 pattern 更有效。"
        ),
    )
    context_lines: int = Field(
        default=3, ge=0, le=20,
        description="每处命中前后各带几行上下文。缺省 3。",
    )
    max_hits: int = Field(
        default=50, ge=1, le=200,
        description="最多返回多少处命中。达到上限时结果里 truncated 为真。",
    )


class ReadSourceArgs(BaseModel):
    """read_source 入参。

    **只接受相对路径**——绝对路径入口一旦存在，这就是个任意文件读取工具，
    能读到 .env 里的凭据（见 change oncall-domain-code 的 design D3）。
    """

    service: str = Field(description="服务名。")
    env: str = Field(description=_ENV_DESC)
    path: str = Field(
        description=(
            "**相对于工作区**的文件路径（如 `src/main/java/com/foo/Bar.java`）。"
            "绝对路径与越出工作区的路径（`../`）都会被拒绝。"
        ),
    )
    start_line: int = Field(default=1, ge=1, description="起始行号（从 1 开始）。")
    line_count: int = Field(
        default=60, ge=1, le=200,
        description="读多少行，上限 200。不提供「读整个文件」——先 code_search 找到行号，再读它周围。",
    )
