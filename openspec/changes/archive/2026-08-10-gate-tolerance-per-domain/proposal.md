## Why

change `oncall-evals-bootstrap` 修掉了三处「按 A 域校准的全局常量，装上 B 域静默失准」的域耦合，**漏了第四处同类的**：门禁容差 `0.30` 仍写死在 [evals/run_evals.py:529](../../../evals/run_evals.py:529)（argparse 默认）与 [evals/run_evals.py:331](../../../evals/run_evals.py:331)（函数默认）。

那个数字是按**预约域**实测最差半宽（槽位 ±28.7pp）定的。值守域实测半宽只有 1.1pp，校准值是 `0.10`。于是现在跑 oncall 门禁必须记得手写 `--tolerance 0.10`——**忘了不会报错，只是松 3 倍**：工具 F1 从 88.9% 掉到 60%（已是工具链崩坏级）照样 PASS。

这与 `GATED_METRICS` 是同一个毛病，只是失准方式更隐蔽：不是少守一项，而是守得太松。文档提醒防不住「忘了带参数」，机制能。

## What Changes

- `EvalProfile` 新增 `tolerance: float` 字段，各域声明自己按实测半宽校准的容差：预约域 `0.30`（照抄现值，行为不变）、值守域 `0.10`。
- `--tolerance` 的默认值从 `0.30` 改为 `None`，语义变为「不传即用当前域声明的容差」；**显式传参仍然覆盖**（排障时手动放宽必须还能用）。
- 门禁报告打印容差时标明来源（域声明 / 命令行覆盖），使「这次用的是哪个容差」在输出里可见，而不用回去翻命令历史。
- `evals/README.md` 删掉「本域跑门禁必须显式带 `--tolerance 0.10`」那条提醒——机制兜住后它就是过期信息。

## Capabilities

### New Capabilities
（无）

### Modified Capabilities
- `eval-harness`: 门禁容差从全局默认值改为读领域包声明，命令行显式传参覆盖声明值。
- `domain-packages`: `EvalProfile` 的内容从三项（标签集合 / 槽位键映射 / 门禁指标集）扩为四项，加入门禁容差。

## Impact

- **修改**：`domains/eval_profile.py`（加字段 + 校验）、`domains/appointment/__init__.py` 与 `domains/oncall/__init__.py`（各自声明）、`evals/run_evals.py`（默认值与解析）、`evals/README.md`（删过期提醒）、`tests/test_eval_profile.py`（补断言）
- **不动**：`compare_to_baseline` 的比对算法（容差一直是它的入参，本次只改「谁来提供这个值」）、基线文件、用例集
- **无需重跑评估**：容差是纯比较阈值，不触网、不调 LLM。「域声明的容差有没有被正确取到」离线单测即可断言，跑真的 `--gate` 换不到额外信号
- **两域基线数字均不变**，预约域容差照抄 `0.30` 故其门禁判定行为等价
