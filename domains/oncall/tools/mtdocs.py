"""mt_docs_search 工具：薄封装 `services/mt_docs.py`。

与 `load_reference` 的分工是本工具 description 的重点——公司自研码与 MT 平台原生码
是**两套体系**，查错地方就查不到。
"""

from __future__ import annotations

from typing import Any

from domains.oncall.tools.schemas import MTDocsSearchArgs
from harness.tools.base import Tool


async def _handler(args: MTDocsSearchArgs) -> dict[str, Any]:
    # 延迟 import：不在加载工具模块时就拉起 sqlite 与配置解析。
    from services.mt_docs import search_mt_docs

    return await search_mt_docs(args.platform.value, args.query, limit=args.limit)


mt_docs_search = Tool(
    name="mt_docs_search",
    description=(
        "检索 MT4 / MT5 **Manager API 官方文档**（接口语义、参数、返回码含义），"
        "返回标题 + 摘录 + 文档链接。\n"
        "\n"
        "⚠ **收录范围是 Manager API，不是 MQL4/MQL5 语言参考**：查得到 "
        "CManagerInterface::TradesRequest、IMTUser::Assign 这类接口；查不到 OrderSend、"
        "iMA 这类 MQL 语言函数——**那不是『没有这个 API』，而是不在本文档库范围内**，"
        "别据此下『该接口不存在』的结论。\n"
        "\n"
        "【先分清查哪儿——两套体系别混】\n"
        "- 公司**自研**码 → 用 load_reference：OCS4 的 nCode/responseCode（66xxx 段、"
        "66302/68302、ENUM_ERR_*）查 ocs4-returncode；OCS5 的 result_code"
        "（0~19 / 4000~4038 / 5000~5174）查 ocs5-returncode。**这些不在 MT 文档里。**\n"
        "- MT **平台原生**码与 API → 先查 mt-returncode 速查表（本地文件、快且省 token）；"
        "**速查表没覆盖时（如 SDK 新增码）才用本工具**。\n"
        "- mtCode 是 MT 服务器返回码（-1 表示无/忽略）；strCodeDesc / responseCodeDesc "
        "是人类可读描述，同行即带、优先看。\n"
        "\n"
        "【怎么判平台】日志里见 CMT4Processor / src/ocs/MT4 / detail{mt4} → mt4；"
        "见 CMT5Processor / detail{mt5} → mt5。**判不出来先问用户，别猜**——"
        "猜错会查出完全无关的结果，而你不会察觉。\n"
        "\n"
        "【检索词】直接给 API 名或返回码常量即可（如 OrderSend、MT_RET_REQUEST_INVALID）。"
        "括号、星号、下划线等特殊字符会被按字面处理，不必转义、也不会报语法错。\n"
        "\n"
        "【回复】把【错误码 + 含义 + 文档链接】一并写进回复，让用户既懂『为什么失败』、"
        "又能自己核对出处。"
    ),
    args_schema=MTDocsSearchArgs,
    handler=_handler,
)
