## 1. 现状盘点（写数据前）

- [x] 1.1 ✅ 已盘点（结果回填 design「现状盘点结果」）：dev 41 条——appointment 20 / query 6 / pay 5 / statistics 5 / other 5，**需新增 109 条**；held-out 10 条需再加 20；带 `expected_outcome` 29 条（22 create_appointment + 7 search_knowledge）；多轮 6 条（均 2 轮）
- [x] 1.2 ✅ 已梳理。**关键发现**：appointment 的 20 条里 10 条（50%）是同一模板（祈使式「时间+时长+项目+力度+性别+具名技师+帮我订好」），系 `evals-stabilize-gate-three` 为稳定门禁而加的冗余锚点；其余各类虽仅 5–6 条但句式各异。据此确定扩容要覆盖的维度：口语/正式、简短/冗长、缺槽待澄清、含噪声（错别字/语气词/夹杂无关内容）、模糊或相对时间、多槽位组合、改约/取消、以及各类的边界表述。**路线已定：多样性优先，接受指标下探**（决策与预期见 design）

## 2. dev 集扩容（每类 ≥30）

- [x] 2.1 `appointment` 扩到 ≥30：含多槽位组合、缺槽待澄清、改约、含噪声表述；有业务终态者标 `expected_outcome: create_appointment`。
- [x] 2.2 `query` 扩到 ≥30：价格/项目/技师/位置等咨询变体；有业务终态者标 `expected_outcome: search_knowledge`。
- [x] 2.3 `pay` 扩到 ≥30：已选定待支付的多种表述（保持 outcome N/A）。
- [x] 2.4 `statistics` 扩到 ≥30：工作人员上报已完成的多种表述（保持 outcome N/A）。
- [x] 2.5 `other` 扩到 ≥30：与按摩无关的干扰/边界表述（保持 outcome N/A）。
- [x] 2.6 在扩容中补若干多轮 `turns` 用例（预约逐步给槽/澄清/改约），字段遵循单轮/多轮互斥约束。

## 3. held-out 集扩容（≥30，覆盖 5 类）

- [x] 3.1 新增 held-out 用例至 ≥30 条、5 类每类 ≥1，`split: "held-out"`；风格与 dev 有意区分（不同措辞/场景）以体检过拟合。
- [x] 3.2 确认 held-out 未复用 dev 原句（防泄漏）。

## 4. 数据自检

- [x] 4.1 跑一次性统计脚本核对：dev 每类 ≥30、held-out ≥30 且覆盖 5 类、schema 合法（单轮/多轮互斥、split ∈ {dev,held-out}、outcome 仅标有工具终态类）。。✅ 自检脚本全绿：184 条无非法项——dev 每类 ≥30（appointment 33 / query 31 / pay 30 / statistics 30 / other 30）、held-out 30 条覆盖 5 类、单轮/多轮互斥、split 合法、工具名合法、`expected_outcome` 只出现在 appointment/query 且必在 `expected_tools` 内、输入无完全重复、held-out 与 dev 无同句（防泄漏）
- [x] 4.2 `uv run python evals/run_evals.py`（默认 dev）能无格式错误加载全部用例；`--include-heldout` 能分集加载 held-out。。✅ `load_cases` 加载 184 条无格式错误；分集过滤正确（默认 dev 154 / include_heldout 184 / heldout_only 30）

## 5. 重定基线（闸门 2 前置）

- [ ] 5.1 `uv run python evals/run_evals.py --samples 3 --update-baseline`（仅 dev）重定 `evals/baseline.json`，人审新基线：意图 / 工具F1 / 槽位的点估计 + CI 是否合理（验收看「CI 收窄 + 分布合理」，非追旧数字）。
- [ ] 5.2 `uv run python evals/run_evals.py --samples 3 --gate` 复核门禁绿。

## 6. 文档同步

- [x] 6.1 `evals/README.md`：记录新规模与每类 ≥30 / held-out ≥30 的下限约定。。✅ 规模下限约定 + 当前实际分布 + **扩容取舍**（多样性优先、不复制既有冗余锚点、指标会下探且不算回归）已写入；并标注既有并发提速实测数字基于 41 条时期、现跑批量约为其 3.8 倍
- [x] 6.2 `docs/agent-eval-fieldguide.md` §12 速查表 + §13 路线图：更新数据规模现状（每类 5→30、held-out 10→30）。。✅ §12 速查表 3 处 + §13 路线图新增「第四切片」条目；顺带修掉 §13 里「门禁实守 3 项（含意图）」的过期说法（意图已随 retire-legacy-intent-classifier 移出，GATED_METRICS 3→2）。baseline 那一格待重定后回填

## 7. 验证与收尾

- [x] 7.1 `uv run pytest`（及 evals 相关测试）绿——成功静默、只报错。 ✅ 449 passed / 9 xfailed（含本切片新增的 15 条数据集自检）
- [ ] 7.2 更新记忆 `eval-progress-state`：数据规模台阶达成、新基线数字、下一步（继续冲几百条 / 其他短板）。

## 8. ⏸ 本切片挂起（2026-08-01 决策）

- [ ] 8.1 **挂起原因**：tasks 5.1/5.2（重定基线 + 门禁复核）需要一次约 64 分钟、数百次真实 LLM 调用的跑批，
  而当前 RAG 处于故障状态（embedding 网关当日在 503/403/200/400 之间反复），此时定出的基线里
  `任务成功率` 与 `回复质量通过率` 都不是有效数字。用户将重构 RAG 为独立服务（见记忆 `rag-eval-deferred`），
  届时一次跑批可同时拿到全部有效指标。
- [ ] 8.2 **⚠ 挂起期间分支 MUST NOT 合并进 master**（不只是不归档）。理由：`baseline.json` 的
  `工具调用-F1 = 56.2%` 基于 41 条旧数据集。若把 184 条新数据集合入却不重定基线，门禁就成了
  「拿新分布比旧基线」——判据变为「实测 > 56.2% − 30pp = 26.2%」，而新构成把 F1 托在 ~78%，
  于是模型即便大幅退化到 40% 门禁仍会 PASS。**门禁会从「能拦回归」退化为「几乎拦不住任何东西」**，
  比不合并糟得多。故 master 保持旧数据集 + 匹配的旧基线，门禁继续有效。
- [ ] 8.3 **恢复时的动作**（两件事必须同一次做完，不可拆开）：把本分支合入 + `--samples 3 --update-baseline`
  重定基线。恢复前先确认 RAG 可用（否则 `任务成功率` 仍是废数）。
- [ ] 8.4 恢复后继续原 tasks 5.1 / 5.2 / 7.2，并按 design「扩容后的实测」一节的判据人审新基线
  （**看 CI 是否收窄 + 分解是否合理，不追旧数字**——旧新两个数不可比，见该节）。
