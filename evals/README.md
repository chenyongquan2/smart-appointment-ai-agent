# evals/ — 重构回归评估集（Phase 0）

> 开发期 harness 的**验证回路**核心。重构前先建基线，重构后逐步对照，防回归。
> 配套：[../docs/harness-refactor-plan.md](../docs/harness-refactor-plan.md) 的 Phase 0。

## 这是什么

一组 `输入 → 期望意图 / 期望工具调用` 的用例。用来在把 `agents/` 重构为 `harness/` 的过程中，**客观衡量**"意图识别 + 工具调用"是否退化——而不是靠"感觉还行"。

## 文件

- `cases.jsonl` — 评估用例（一行一条 JSON；`//` 开头的行为注释，运行时跳过）。
- `run_evals.py` — 运行器（**当前是骨架**：加载并校验用例、打印；接入真实 agent 后输出准确率）。

## 用例格式

```json
{"input": "我想预约明天下午的按摩", "expected_intent": "appointment", "expected_tools": ["find_technician", "check_availability"]}
```

## 运行

```bash
uv run python evals/run_evals.py
```

## 待办（Phase 0 正式落地时）

- [ ] 按项目**实际**的 category 枚举与工具名，校准 `cases.jsonl` 里的 `expected_*`。
- [ ] 扩充到 ~20 条，覆盖：预约 / 咨询 / 多槽位 / 缺槽位追问 / 改约 / 边界输入。
- [ ] 在 `run_evals.py` 里接入真实分类/agent，逐条比对，**输出准确率基线**。
- [ ] 把"跑 evals"接入 `/phase` 的验证闸门（闸门 2）。
