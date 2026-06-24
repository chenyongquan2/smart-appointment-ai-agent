## 1. judge 调用层（evals/judge.py，触网、可注入）

- [x] 1.1 定义结构化裁决 schema `JudgeVerdict {reason: str, pass: bool}`（reason 字段在前，引导先推理后裁决）
- [x] 1.2 `judge_response(user_input, reply, llm)`：用明确 rubric（恰当+正确+有帮助；按内容不按长度）构 prompt，structured output 返回 JudgeVerdict；temperature=0；llm 可注入
- [x] 1.3 单测：注入脚本化 fake judge LLM，断言裁决被正确解析为 {pass, reason}（离线、不触网）

## 2. 回复采集（evals/agent_capture.py）

- [x] 2.1 扩展为同时 surface agent 最终回复文本（如 `run_and_capture(...) -> {tool_calls, reply}`）
- [x] 2.2 `capture_tool_calls` 保留为薄封装回 `.tool_calls`（改造 1 既有测不破）
- [x] 2.3 单测：fake LLM 驱动，断言最终回复文本被正确 surface

## 3. 裁决聚合 + 校准（evals/metrics.py，纯函数）

- [x] 3.1 `response_quality(verdicts)`：质量通过率（pass 占比）；无裁决 → 显式 N/A，不伪造分母
- [x] 3.2 `judge_human_agreement(judge_labels, human_labels)`：二元一致率 + Cohen's κ（纯函数）
- [x] 3.3 报告渲染：回复质量行；人工校准缺失时显式标「未校准（κ 未测）」
- [x] 3.4 单测：response_quality（含 N/A）、κ 计算（含完全一致 κ=1、随机 κ≈0）、未校准标注

## 4. 接线 + 校准占位（evals/run_evals.py + calibration.jsonl）

- [x] 4.1 `--judge` 开关（默认关）；开启时每条用例对采集到的回复调 judge，填裁决
- [x] 4.2 把 response_quality 纳入报告；judge 开启但未校准 → 报告带「未校准」标注与自我偏好局限提示
- [x] 4.3 新增 `evals/calibration.jsonl` 占位（含格式说明注释，供人工填真实 {input, reply, human_pass}）

## 5. 测试 + 验证（闸门 2）

- [x] 5.1 `uv run pytest` 全绿（含新测与既有回归），成功静默、只暴露失败
- [x] 5.2 软验收：有 key 时 `--judge --limit 4` 真跑，报告出现回复质量通过率 + 「未校准」标注（只看结构，不断言数值）
- [x] 5.3 确认 out-of-scope 未被牵入（无 pairwise/位置互换、无 RAG 三元组、无伪造人工标注、无基线阈值阻断）
