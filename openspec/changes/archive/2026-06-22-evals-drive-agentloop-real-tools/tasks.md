## 1. 修盲区：tracer 透传进子 Agent loop（harness/）

- [x] 1.1 `SubAgent.run` 增加可选 `tracer` 参数，构造内层 `AgentLoop` 时透传（缺省 `None` → 退化 `NoopTracer`，行为不变）
- [x] 1.2 `build_delegate_tool` / `delegate` handler 增加可选 `tracer` 并向 `SubAgent.run` 透传
- [x] 1.3 新增单测：注入真 `Tracer` 派生子 Agent 后，导出的 span 含子 Agent 步内的 `tool_call`+`observation`（对应 observability spec 场景一）
- [x] 1.4 新增单测：未注入 tracer（NoopTracer）时子 Agent 无 span 导出、行为与改造前一致（向后兼容场景）

## 2. 数据模型：actual_tools 采全（evals/metrics.py）

- [x] 2.1 `EvalResult.actual_tools` 从 `list[str]` 改为有序 `list[{name, args}]`（采全）
- [x] 2.2 `tool_call_correctness` 适配新形状但保持 `set` 名字集合比较语义（参数/顺序不参与）
- [x] 2.3 调整 `tests/test_eval_metrics.py` 适配字段形状，断言意图不变（仍 N/A 逻辑 + set 比较）

## 3. 工具调用采集：span → 有序工具序列（evals/）

- [x] 3.1 写一个纯函数：从一组 span 收集所有 `tool_call` 事件，按 `(span.start, 事件顺序)` 还原有序 `[{name, args}, ...]`（不按单一 trace_id 过滤）
- [x] 3.2 新增单测：喂入「跨多棵子 Agent trace 树」的合成 span，断言还原序列正确（对应 eval-harness「采集覆盖子 Agent」场景）

## 4. 真跑路径：run_evals 驱动端到端 AgentLoop（evals/run_evals.py）

- [x] 4.1 用 `build_default_registry()` + `build_default_subagent_registry()` + `build_delegate_tool()` 构造带真 `Tracer(InMemoryExporter())` 的主 loop（不复用 chat_handler 单例）
- [x] 4.2 逐条用例：新建独立 exporter 沙盒 → 跑主 loop → 用 3.1 的函数采集 → 填 `EvalResult.actual_tools`
- [x] 4.3 保留意图分类准确率路径（与真跑并存）；真跑仅在 `_has_api_key()` 为真时启用，无 key 沿用既有优雅降级
- [x] 4.4 新增单测：`ScriptedChatModel` 脚本化吐 `delegate → 子 Agent 工具调用`，断言 `actual_tools` 被填、`tool_call_correctness` 从 N/A 翻成真实数字（对应 eval-harness「不再恒 N/A」场景）

## 5. 验证（闸门 2）

- [x] 5.1 `uv run pytest` 全绿（含 1.3/1.4/3.2/4.4 新测与既有回归），成功静默、只暴露失败 —— 169 passed, 9 xfailed
- [x] 5.2 手动冒烟：有 key 时 `uv run python evals/run_evals.py --limit 2` 跑完，工具调用正确率从 N/A 翻成真实数字（0.0% 2/2，结构正确），管道通
- [x] 5.3 确认 out-of-scope 未被牵入（无参数级/序列级比对、无基线阈值阻断、无 C-full 嵌套）
