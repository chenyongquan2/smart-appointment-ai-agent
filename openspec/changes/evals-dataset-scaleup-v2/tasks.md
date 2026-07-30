## 1. 现状盘点（写数据前）

- [ ] 1.1 统计 `evals/cases.jsonl` 现状：dev 各类计数、held-out 计数、带 `expected_outcome` 的条数、多轮 `turns` 条数——确定每类还差多少条到 30、held-out 还差多少到 30。
- [ ] 1.2 梳理各类现有句式，列出扩容要覆盖的多样性维度清单（口语/正式、简/繁、边界、含噪声、多槽位组合），避免造出近似重复。

## 2. dev 集扩容（每类 ≥30）

- [ ] 2.1 `appointment` 扩到 ≥30：含多槽位组合、缺槽待澄清、改约、含噪声表述；有业务终态者标 `expected_outcome: create_appointment`。
- [ ] 2.2 `query` 扩到 ≥30：价格/项目/技师/位置等咨询变体；有业务终态者标 `expected_outcome: search_knowledge`。
- [ ] 2.3 `pay` 扩到 ≥30：已选定待支付的多种表述（保持 outcome N/A）。
- [ ] 2.4 `statistics` 扩到 ≥30：工作人员上报已完成的多种表述（保持 outcome N/A）。
- [ ] 2.5 `other` 扩到 ≥30：与按摩无关的干扰/边界表述（保持 outcome N/A）。
- [ ] 2.6 在扩容中补若干多轮 `turns` 用例（预约逐步给槽/澄清/改约），字段遵循单轮/多轮互斥约束。

## 3. held-out 集扩容（≥30，覆盖 5 类）

- [ ] 3.1 新增 held-out 用例至 ≥30 条、5 类每类 ≥1，`split: "held-out"`；风格与 dev 有意区分（不同措辞/场景）以体检过拟合。
- [ ] 3.2 确认 held-out 未复用 dev 原句（防泄漏）。

## 4. 数据自检

- [ ] 4.1 跑一次性统计脚本核对：dev 每类 ≥30、held-out ≥30 且覆盖 5 类、schema 合法（单轮/多轮互斥、split ∈ {dev,held-out}、outcome 仅标有工具终态类）。
- [ ] 4.2 `uv run python evals/run_evals.py`（默认 dev）能无格式错误加载全部用例；`--include-heldout` 能分集加载 held-out。

## 5. 重定基线（闸门 2 前置）

- [ ] 5.1 `uv run python evals/run_evals.py --samples 3 --update-baseline`（仅 dev）重定 `evals/baseline.json`，人审新基线：意图 / 工具F1 / 槽位的点估计 + CI 是否合理（验收看「CI 收窄 + 分布合理」，非追旧数字）。
- [ ] 5.2 `uv run python evals/run_evals.py --samples 3 --gate` 复核门禁绿。

## 6. 文档同步

- [ ] 6.1 `evals/README.md`：记录新规模与每类 ≥30 / held-out ≥30 的下限约定。
- [ ] 6.2 `docs/agent-eval-fieldguide.md` §12 速查表 + §13 路线图：更新数据规模现状（每类 5→30、held-out 10→30）。

## 7. 验证与收尾

- [ ] 7.1 `uv run pytest`（及 evals 相关测试）绿——成功静默、只报错。
- [ ] 7.2 更新记忆 `eval-progress-state`：数据规模台阶达成、新基线数字、下一步（继续冲几百条 / 其他短板）。
