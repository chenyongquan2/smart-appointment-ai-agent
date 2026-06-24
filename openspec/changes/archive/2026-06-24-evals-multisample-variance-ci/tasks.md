## 1. CI 纯函数（evals/metrics.py）

- [x] 1.1 硬编码 95% 双侧 t 临界值小表（df 1–30），零依赖；超范围有明确退化策略
- [x] 1.2 纯函数 `aggregate_runs`：吃一组 per-run 的同名指标值，算 mean / 样本标准差 s / t 分布 CI 半宽（`t·s/√N`）；N=1 与 s=0 时 CI 半宽=0
- [x] 1.3 渲染：报告对多采样指标输出 `mean ± half_width（n=N）`，并标注 CI 为 run-to-run（LLM 抖动）、不含数据集误差

## 2. 采样循环（evals/run_evals.py）

- [x] 2.1 加 `--samples N` 参数（默认 1）；N=1 时走原单次路径、报告不含 CI 列（向后兼容）
- [x] 2.2 N>1 时整套用例独立重跑 N 次，每次收集一组聚合指标值；顺序执行
- [x] 2.3 跨 N 次调 `aggregate_runs` 汇总为 mean±CI，交报告渲染；保留无 key 优雅降级

## 3. 测试 + 验证（闸门 2）

- [x] 3.1 离线确定性单测：t 值表正确（抽查几个 df）、aggregate_runs 正常多值 mean±CI 正确、N=1 半宽=0、零方差半宽=0
- [x] 3.2 单测：N=1 报告不含 CI（向后兼容）、N>1 报告含 `± half_width（n=N）` 且标注含义
- [x] 3.3 `uv run pytest` 全绿（含新测与既有回归），成功静默、只暴露失败
- [x] 3.4 软验收：有 key 时 `--samples 3 --limit 4` 真跑，报告出现 mean±CI；temp=0 下若零方差则点值+标注稳定（只看结构，不断言数值）
- [x] 3.5 确认 out-of-scope 未被牵入（无 pass@k、无并发、无基线阈值阻断、无数据集误差声称）
