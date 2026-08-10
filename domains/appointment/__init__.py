"""预约域领域包 —— 按摩/推拿门店的咨询与预约。

这是本项目的原始领域，随 change `domain-packages` 从 `harness/` 下沉至此。它同时是
「换域 = 换五样东西」这条设计判断的**参照实现**：第 3 期的 oncall 域照同一形状填即可。

五个槽位：

| 槽位 | 在哪 |
|---|---|
| 工具集 | `tools/`（5 个，薄封装 `services/`） |
| 子 Agent 集 | `subagents/`（预约 / 咨询 / 行为分析） |
| 系统提示 | `prompt.py` |
| 权限策略 | `policy.py` |
| 评估数据与标注口径 | `evals/`（`cases.jsonl` + `baseline.json`）+ 下面的 `_EVAL_PROFILE`，**只有数据与口径在这，机制留在 `evals/`** |
"""

from __future__ import annotations

from pathlib import Path

from domains import Domain, EvalProfile

__all__ = ["build_domain"]

# 数据目录用「相对本文件」定位而非 cwd：评估既可能从仓库根跑，也可能从别处跑。
_EVALS_DIR = Path(__file__).parent / "evals"

# 评估标注口径（change oncall-evals-bootstrap）。三项**原样搬自** evals/ 里此前的全局
# 硬编码常量（VALID_INTENTS / _SLOT_ARG_KEYS / GATED_METRICS），故本域行为与基线数字
# 一字不动、**无需重定基线**——这是那次重构的等价性锚点。
_EVAL_PROFILE = EvalProfile(
    # 5 类意图口径。纯数据集元数据：旧分类器已随 change retire-legacy-intent-classifier
    # 删除，这些标签不再对应任何组件，只管覆盖约束/分项分析/切分规则。
    labels=frozenset({"appointment", "query", "pay", "statistics", "other"}),
    # 门禁守正确性子集。刻意排除延迟（环境噪声）、回复质量（judge 未校准）、
    # 以及工具调用的其余分档（同一底层行为，只守 F1 即可）。
    gated_metrics=("工具调用-F1", "槽位抽取完整率"),
    # 容差（change gate-tolerance-per-domain）：照抄此前的全局默认值，故本域门禁判定
    # 行为等价。依据是本域实测最差半宽——槽位完整率 ±28.7pp（41 条 dev × 3，干净跑）。
    tolerance=0.30,
    # 工具入参名 → 统一槽位键。technician_name 归一为 technician（对齐 AppointmentSlots）；
    # create_appointment 的 technician_id/session_id 是 ID/会话基建、不是「抽取槽位」，不在此。
    slot_key_map={
        "start_time": "start_time",
        "duration": "duration",
        "project": "project",
        "preference": "preference",
        "gender": "gender",
        "technician_name": "technician",
    },
)


def build_domain() -> Domain:
    """组装预约域。由 `domains.load_domain()` 调用。

    函数内 import 的理由同 `domains/__init__.py` 的注册表：装本域时才拉起本域依赖。
    """
    from domains.appointment.policy import POLICY
    from domains.appointment.prompt import SYSTEM_PROMPT
    from domains.appointment.subagents import SUBAGENTS
    from domains.appointment.tools import TOOLS

    return Domain(
        name="appointment",
        tools=TOOLS,
        subagents=SUBAGENTS,
        system_prompt=SYSTEM_PROMPT,
        policy=POLICY,
        evals_dir=_EVALS_DIR,
        eval_profile=_EVAL_PROFILE,
    )
