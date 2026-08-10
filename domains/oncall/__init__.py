"""OnCall 值守域领域包 —— 查日志、定位线上问题。

按 change `domain-packages` 定下的五槽位填。与预约域的差别值得记一笔：

| 槽位 | 预约域 | 值守域 |
|---|---|---|
| tools | 5 个（含 1 个写库） | 2 个，**全只读** |
| subagents | 3 个专员 | **空**（见 subagents/__init__.py 的理由） |
| prompt | 门店助手人设 | 值守人设 + 只读红线 + 排查分诊表 |
| policy | allow_all | **拒绝一切 dangerous 工具** |
| evals | 51 条用例 + 口径 | 本域用例集 + 口径（门禁守参数级 F1，不守槽位完整率） |

本域是「换域 = 换五样东西、运行时一行不动」这条判断的第一次实检。
"""

from __future__ import annotations

from pathlib import Path

from domains import Domain, EvalProfile

__all__ = ["build_domain"]

_EVALS_DIR = Path(__file__).parent / "evals"

# 评估标注口径（change oncall-evals-bootstrap）。三项都与预约域不同，这正是把它们
# 下沉进领域包的理由。
_EVAL_PROFILE = EvalProfile(
    # 5 类标签按**工具族**划分，刻意与工具集对齐——这样「每类不少于 5 条」这条覆盖约束
    # 直接翻译成工具覆盖，用例集不会不知不觉全长在最好写的 vlog_query 上。
    # 与预约域的 5 类**毫无关系**，两域标签 MUST NOT 混用或互相比较。
    labels=frozenset({
        "log_triage",        # 查日志排障（traceId / 报错片段 / 告警时刻下钻）
        "code_lookup",       # 定位与只读检索服务源码
        "docs_lookup",       # 查 MT4/MT5 平台文档与返回码
        "reference_lookup",  # 加载排查资料（服务档案 / 各类错误码表）
        "other",             # 与值守排障无关的输入
    }),
    # 第二道门禁用**参数级 F1** 而非槽位完整率（design D3）。理由是口径不是省事：
    # 本域判别性入参（service/env/platform/name）几乎全是必填项或枚举，槽位完整率是
    # **存在性**口径——只要工具被调用就恒命中，它会退化成工具 F1 的影子，两项守同一个
    # 信号。反过来，正因这些值是枚举/短字面量，**精确值比对**在这里成立；而预约域参数级
    # F1 只有 11.1% 恰恰是因为它的值是自由文本（start_time 常算错）。同一指标，两域适用性相反。
    gated_metrics=("工具调用-F1", "工具调用-参数级F1"),
    # 容差（change gate-tolerance-per-domain）：实测最差半宽 1.1pp（参数级 F1，36 条
    # dev × 3），留约 9 倍余量应对 n=3 半宽估计本身的不稳；比预约域的 0.30 紧 3 倍。
    # **不是**沿用任何全局值——跨域容差互相沿用会静默地守得过松或过紧。
    tolerance=0.10,
    # 空映射 = **本域不度量槽位完整率**（显式声明，不是忘了配）。硬凑一份把必填项也算
    # 槽位的映射，等于制造一个恒 ~100% 的指标来充数，属于粉饰门禁。
    slot_key_map={},
)


def build_domain() -> Domain:
    """组装值守域。由 `domains.load_domain()` 调用。"""
    from domains.oncall.policy import POLICY
    from domains.oncall.prompt import SYSTEM_PROMPT
    from domains.oncall.subagents import SUBAGENTS
    from domains.oncall.tools import TOOLS

    return Domain(
        name="oncall",
        tools=TOOLS,
        subagents=SUBAGENTS,
        system_prompt=SYSTEM_PROMPT,
        policy=POLICY,
        evals_dir=_EVALS_DIR,
        eval_profile=_EVAL_PROFILE,
    )
