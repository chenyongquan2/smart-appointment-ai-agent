## 1. EvalProfile 加容差字段

- [x] 1.1 `domains/eval_profile.py`：加 `tolerance: float` 字段与区间校验（`0.0 <= t < 1.0`，`0.0` 放行=零容忍）；docstring 写明「容差必须覆盖实测半宽」是流程约束、代码无从校验（design D2）
- [x] 1.2 `domains/appointment/__init__.py`：声明 `tolerance=0.30`（照抄现值，行为不变）
- [x] 1.3 `domains/oncall/__init__.py`：声明 `tolerance=0.10`（实测最差半宽 1.1pp，留约 9 倍余量）

## 2. 运行器改读域声明

- [x] 2.1 `evals/run_evals.py`：argparse `--tolerance` 默认值 `0.30` → `None`（哨兵法，design D1），help 文本改为「不传即用当前域声明的容差」
- [x] 2.2 `evals/run_evals.py`：`run_baseline` 的 `tolerance` 参数默认改 `None`，比对前解析——显式值优先，否则取 `load_domain().eval_profile.tolerance`
- [x] 2.3 门禁报告标明容差来源（`来自域 'X' 声明` / `命令行覆盖`），与判定结论同处输出（design D3）
- [x] 2.4 确认 `evals/` 里不再有任何按具体域校准的容差默认值（grep `0.30` / `0.20`）

## 3. 测试

- [x] 3.1 `tests/test_eval_profile.py`：补两域容差断言，字面量**写死在测试里**（预约域 `0.30` / 值守域 `0.10`），与该文件既有等价性锚点同范式
- [x] 3.2 补校验测试：容差超区间（`1.0` / 负数）构造即报错；`0.0` 合法
- [x] 3.3 补解析测试：不传时取域声明值、显式传时覆盖域声明值（离线，不触网）
- [x] 3.4 `uv run pytest` 全绿

## 4. 文档

- [x] 4.1 `evals/README.md`：删掉「本域跑门禁必须显式带 `--tolerance 0.10`」那条提醒（机制兜住后是过期信息），改为说明容差随域声明、显式传参覆盖
- [x] 4.2 `evals/README.md`：把两域的校准依据（预约域 ±28.7pp → `0.30`；值守域 ±1.1pp → `0.10`）与「跨域容差不得互相沿用」写在一处
