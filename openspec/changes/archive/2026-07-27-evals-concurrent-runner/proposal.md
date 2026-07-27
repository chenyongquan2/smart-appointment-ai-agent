# 评估运行器并发化

## Why

评估当前逐条串行真跑：41 条 dev 用例 × 端到端 27s ≈ **单次跑 18 分钟、`--samples 3` 重定基线约 1 小时**。慢是根因，连锁出三个问题：

1. **反馈延迟**——一个 change 改了多处才跑一次门禁，回归了要二分查找是哪一步引入的；
2. **频率被成本压制**——20 分钟的检查没人愿意随手跑，"想跑"和"愿意跑"之间被成本隔开；
3. **长跑暴露于网络抖动**——本 change 前置的两次重定基线，第一次即因 `APIConnectionError` 大批失败作废（跑越久，撞上抖动的概率越大）。

用例之间本就相互独立（每条一个独立 `Tracer` + `InMemoryExporter` 沙盒，见 `evals/agent_capture.py` D3），串行不是正确性要求，只是实现方式。并发化是投入产出比最高的一项：**单次跑压到 2–4 分钟后，门禁才可能高频、夜间定时跑才划算**。

## What Changes

- `evals/run_evals.py` 的 `_run_once` 从 `for case in cases` 串行改为**受限并发**：`asyncio.gather` + `asyncio.Semaphore(N)`，N 经 `--concurrency` 配置（默认保守值，见 design）
- **结果顺序 MUST 与 `cases` 同序**（下游 `_split_results` 依赖 zip 同序同长）
- **失败隔离不变**：单条异常仍记 N/A、不拖垮全量；并发下 MUST NOT 因一条异常取消其它任务
- **延迟指标口径澄清**：并发下每条的 `latency_s` 含资源竞争，MUST 在报告注明「并发跑的延迟含竞争、不可与串行跑的历史数字直接比」；延迟不在门禁，无回归判定影响
- `--concurrency 1` 退化为串行，行为与本变更前等价（向后兼容 + 排障用）
- 评估侧 DB 并发安全性核查与必要加固（SQLite + `scoped_session`，见 design D3）

**不改**：harness、services、指标口径、用例集、门禁逻辑。

## Capabilities

### New Capabilities

（无——并发是既有 eval-harness 能力的执行方式变更）

### Modified Capabilities

- `eval-harness`: 新增「用例并发执行」需求（受限并发、同序返回、失败隔离、`--concurrency 1` 等价串行）；「多指标评估报告」的延迟需求补充并发口径标注

## Impact

- 修改：`evals/run_evals.py`（`_run_once` + CLI 参数）、`evals/README.md`（并发用法与延迟口径说明）
- 可能修改：`db/base/session_manager.py`（若核查发现 `scoped_session` 在 asyncio 并发下不安全，见 design D3）
- 新增单测：并发同序、失败隔离、并发上限生效、`--concurrency 1` 等价串行（全部注入 fake，离线确定性）
- **基线**：并发化后需重定基线一次——**不是因为指标口径变了**（比率型指标不受并发影响），而是延迟数字会因竞争上移；另需实测确认比率型指标的均值与半宽无系统性漂移（若有漂移即说明并发引入了污染，属实现缺陷需修复而非接受）
- 验证：`uv run pytest` 全绿；并发跑与串行跑的比率型指标在容差内一致
