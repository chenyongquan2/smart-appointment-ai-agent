"""领域包的**评估标注口径**声明。

为什么这三项属于领域包而不是 `evals/`：评估机制要读一份用例，就必须先知道
「本域的标签叫什么、哪些工具入参算槽位、本域实际能守哪些指标」。这三件事**换个域
就不成立**，按 `domain-packages` 的判据属域绑定内容。它们此前写死在 `evals/` 里，
使「机制域无关」名不副实——装上另一个域的数据要么直接加载失败（标签白名单），
要么门禁**静默**退化成守更少的项（见 change `oncall-evals-bootstrap` 的 design）。

**本模块是纯声明**：指标怎么算、门禁怎么比对仍留在 `evals/`。这里只做结构性校验
（非空、类型）；「指标名是否真实存在」这类**语义**校验在 `evals/` 侧做——指标名全集
在 `evals/metrics.py`，而依赖方向是 `evals → domains`，反过来 import 会成环。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

__all__ = ["EvalProfile"]


@dataclass(frozen=True)
class EvalProfile:
    """一个域的评估标注口径。

    Attributes:
        labels: 本域数据集的 `expected_intent` 标签白名单。**纯数据集元数据**——不喂
            任何分类器（旧分类器已退役），只用于覆盖约束、按类分项分析与切分规则。
            没有它，用例集会不知不觉全长在最容易写的那个工具上。
            跨域标签 MUST NOT 混用或互相比较。
        slot_key_map: 工具入参名 → 槽位键 的归一映射，喂「槽位抽取完整率」。
            **允许为空**，语义是「本域不度量槽位完整率」（该指标恒 N/A、且不得进门禁）——
            这是显式声明，不是「忘了配」。值守域即为此例：其判别性入参几乎全是必填项
            或枚举，存在性口径下只要工具被调用就恒命中，该指标会退化成工具 F1 的影子。
            带 schema 默认值的入参 MUST NOT 声明为槽位键——默认值恒存在会使完整率虚高，
            与「哨兵值 `未知`/`无` 不算已填」是同一条原则。
        gated_metrics: 本域门禁守护的指标名。**不允许为空**——「一个都不守」等于没有
            门禁，必须显式暴露而非默许。指标名是否真实存在、是否属被禁的说明性指标，
            由 `evals/` 侧校验（见模块 docstring 的分层理由）。
    """

    labels: frozenset[str]
    gated_metrics: tuple[str, ...]
    # 缺省空映射 = 本域不度量槽位完整率。放最后并给缺省值，使「不度量」是一句话的事。
    slot_key_map: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 结构性校验只管「形状对不对」，坏声明在**装载那一刻**就炸，而不是等跑到一半
        # 才表现为「指标莫名 N/A」。这与 Domain 用 frozen dataclass 的理由一致：
        # 「这个部署有哪些能力」必须在装载时就定死。
        if not isinstance(self.labels, frozenset) or not self.labels:
            raise ValueError("EvalProfile.labels 必须是非空 frozenset[str]")
        if not all(isinstance(x, str) and x for x in self.labels):
            raise ValueError("EvalProfile.labels 的每一项必须是非空字符串")
        if not isinstance(self.gated_metrics, tuple) or not self.gated_metrics:
            # 空集刻意不放行：门禁一项不守却返回 0，是最坏的那种「看起来通过了」。
            raise ValueError(
                "EvalProfile.gated_metrics 必须是非空 tuple[str, ...]；"
                "「一个都不守」等于没有门禁，须显式暴露而非默许"
            )
        if not all(isinstance(x, str) and x for x in self.gated_metrics):
            raise ValueError("EvalProfile.gated_metrics 的每一项必须是非空字符串")
        if len(set(self.gated_metrics)) != len(self.gated_metrics):
            raise ValueError(f"EvalProfile.gated_metrics 含重复项：{self.gated_metrics}")
        if not isinstance(self.slot_key_map, Mapping):
            raise ValueError("EvalProfile.slot_key_map 必须是 Mapping[str, str]")
        if not all(
            isinstance(k, str) and k and isinstance(v, str) and v
            for k, v in self.slot_key_map.items()
        ):
            raise ValueError("EvalProfile.slot_key_map 的键与值都必须是非空字符串")
        # frozen dataclass 只冻结「字段绑定」，不深冻内容——传进来的 dict 调用方仍能改。
        # 包一层只读视图，兑现「装载后没人能偷偷改口径」这条承诺（同 Domain 的 frozen 理由）。
        object.__setattr__(self, "slot_key_map", MappingProxyType(dict(self.slot_key_map)))

    @property
    def measures_slots(self) -> bool:
        """本域是否度量槽位完整率。

        供报告侧区分两种 N/A：**本域不度量**（空映射，恒 N/A、是设计）与
        **本次未捕获**（真跑失败/未触发工具，是抖动）。两者混为一谈会让人误以为
        指标坏了、或反过来误以为一切正常。
        """
        return bool(self.slot_key_map)
