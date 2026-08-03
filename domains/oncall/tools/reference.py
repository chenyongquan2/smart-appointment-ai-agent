"""load_reference 工具：按需加载排查资料。

为什么要"按需"：4 份资料共约 97KB，全量塞进上下文既贵又稀释注意力。参考系统的做法是
「路由表 + 命中才读」——路由表（20 行）进系统提示，本体经本工具按需读。

为什么入参是**枚举而非路径**：自由路径等于给模型一个任意文件读取能力，是权限漏洞。
新增资料要同时改三处：`references/` 放文件、`schemas.ReferenceName` 加枚举、
`prompt.py` 的分诊表加行。有测试守着枚举与文件的一致性。
"""

from __future__ import annotations

from pathlib import Path

from domains.oncall.tools.schemas import LoadReferenceArgs
from harness.tools.base import Tool

# 相对本文件定位，不依赖 cwd（服务可能从任意目录起）。
REFERENCES_DIR = Path(__file__).resolve().parent.parent / "references"


async def _handler(args: LoadReferenceArgs) -> dict[str, str]:
    path = REFERENCES_DIR / f"{args.name.value}.md"
    # 枚举已在校验层限死取值，这里再确认一次文件真的在——枚举与文件不同步时
    # 要给出可排查的错误，而不是让 FileNotFoundError 裸奔进模型上下文。
    if not path.is_file():
        raise FileNotFoundError(
            f"排查资料 '{args.name.value}' 已登记但文件缺失（{path.name}）。"
            "这是仓库内的不一致，请联系维护者，不要据此推断线上状态。"
        )
    return {"name": args.name.value, "content": path.read_text(encoding="utf-8")}


load_reference = Tool(
    name="load_reference",
    description=(
        "按名加载排查资料（服务档案 / 各体系返回码表）。何时该读哪一份，见系统提示里的"
        "分诊表——命中信号才读，通用查询（traceId / vmui 链接 / 关键词+环境）直接查、不读。\n"
        "可选：ocs-service-profiles（环境清单、定位字段、日志格式、根因线索；"
        "**清单类问题直接读它回答、不要查日志**）、mt-returncode、ocs4-returncode、"
        "ocs5-returncode。\n"
        "资料里标 <待填> / TODO 的条目是未确认知识，不得当真、不得据此编造字段。"
    ),
    args_schema=LoadReferenceArgs,
    handler=_handler,
)
