# 设计：评估运行器并发化

## Context

`_run_once` 逐条串行真跑，41 条 × 27s ≈ 18 分钟/次。用例之间无共享可变状态：`agent_capture._build_capture_loop` 为**每条用例新建** `InMemoryExporter` + `Tracer` + `AgentLoop`（design D3「每条用例一个 exporter 沙盒」），`AgentLoop` 本身无状态。跨用例共享的只有三样：`llm`（`BaseChatModel`）、`full_registry`（工具→services→DB）、`subagents`。串行是历史实现方式，不是正确性要求。

## Goals / Non-Goals

**Goals:**
- 单次跑从 ~18 分钟压到 2–4 分钟（并发 6~8 时的理论量级）
- 结果同序、失败隔离、可退化为串行——三条不可妥协
- 比率型指标（工具 F1/槽位等）并发前后无系统性漂移

**Non-Goals:**
- 不改指标口径、不改用例集、不改门禁逻辑
- 不追求极限并发（网关限流与本地 SQLite 是硬约束，宁保守）
- 不做跨进程并行

## Decisions

### D1 `asyncio.gather` + `Semaphore`，不引入线程/进程池

真跑全程是 IO 等待（LLM 调用），asyncio 天然合适；`gather` **保序返回**，正好满足下游 `_split_results(cases, results)` 的 zip 同序要求。线程池会把 SQLite 的线程亲和问题一起引进来，无必要。

```python
sem = asyncio.Semaphore(concurrency)
async def _one(case):
    async with sem:
        return await _run_case(case, ...)
results = await asyncio.gather(*(_one(c) for c in cases))
```

### D2 并发默认值取 5，`--concurrency` 可调；`1` 等价串行

保守起步的三条依据：网关限流未知（本 change 前置基线跑已实测到 embedding 渠道 503 与 `APIConnectionError`）；每条用例内部还会派生子 Agent、实际在途请求数是并发数的数倍；SQLite 写锁。5 已能把 18 分钟压到 ~4 分钟，收益的大头已拿到。实测稳定后可再调。

`--concurrency 1` MUST 与本变更前逐条串行**行为等价**（不只是"看起来一样"）——它是排障与对照的基准路径。

### D3 DB 并发：先核查，按实测决定是否加固

`db/base/session_manager.py` 用 `scoped_session`（线程局部）+ 默认 SQLite 引擎。asyncio 单线程并发下，所有协程落在**同一线程 → 共享同一个 session**，这与"每次 `session_scope()` 独立事务"的假设冲突：协程 A 的 `commit()` 会提交协程 B 的未完成写入，交错时还可能触发 `session.close()` 抢跑。

处置顺序（先证据后动手，不臆测重构）：
1. 实现首步先跑**并发只读冒烟**（query 类用例，只读工具），确认是否报错；
2. 再跑含写入的预约类用例（`create_appointment`），观察 `database is locked` / 事务交错；
3. 若确有问题，最小加固：评估路径改用 `asyncio.to_thread` 包裹 DB 调用，或把 `scoped_session` 的 scopefunc 改为 `asyncio.current_task`（后者影响生产代码，需谨慎并单独评估）。

**MUST NOT** 为并发化重写 `db/`——那是 CLAUDE.md 的"不要重写"清单内容。若加固代价超出本 change 范围，宁可降低默认并发数或限定只读并发。

### D4 延迟指标：如实标注，不做补偿

并发下 `latency_s` 含资源竞争，必然高于串行。**不做任何"扣除竞争"的补偿计算**（无法诚实计算）。做法：报告注明口径、README 记录"并发跑的延迟不可与串行历史数字直接比"。延迟不在 `GATED_METRICS`，无回归判定影响。

### D5 验收靠"并发 vs 串行"对照，不只看跑得快

实现后 MUST 跑一次对照：同一份用例集分别 `--concurrency 1` 与 `--concurrency 5` 各跑，比对**比率型指标**。若并发跑的工具 F1/槽位完整率相对串行出现系统性偏移（超出既有实测半宽），说明并发引入了污染（DB 交错、限流致失败增多等），**属实现缺陷 MUST 修复，MUST NOT 当作新常态接受并重定基线**。

## Risks / Trade-offs

- [网关限流致失败率上升，污染指标] → 默认并发保守（5）；D5 对照验收会暴露；必要时降并发。
- [SQLite 事务交错致写入错乱] → D3 分步核查；最坏退化为"只读并发、写入串行"或降低并发。
- [并发下日志交错难排障] → 保留 `--concurrency 1` 作为排障基准路径。
- [基线需重定一次（延迟数字上移）] → 一次性成本；且并发化后重定基线本身只需几分钟，成本大幅低于现状。

## Migration Plan

1. `_run_once` 并发改造 + CLI 参数 + 离线单测（fake，验同序/隔离/上限/串行等价）
2. 并发只读冒烟 → 含写入冒烟（D3 核查）
3. D5 对照跑（`--concurrency 1` vs `5`），比率型指标一致才算通过
4. 重定基线（此时只需几分钟）+ `--gate` 验证

回滚：`--concurrency 1` 即恢复旧行为；代码回滚 = revert 本 PR。

## Open Questions

- 网关实际限流阈值未知——靠 D5 对照与冒烟实测摸边界，不预设
