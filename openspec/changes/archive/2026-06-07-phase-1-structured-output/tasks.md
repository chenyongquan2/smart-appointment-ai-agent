## 1. 定义 Pydantic schema

- [x] 1.1 在 `agents/task_classification/` 下定义 `TaskCategory`（`category: Literal["appointment","query","pay","statistics","other"]`，可选 `confidence: float`、`reason: str`），含字段说明
- [x] 1.2 在 `agents/appointment/` 下定义 `AppointmentSlots`，覆盖 `gender/start_time/duration/project/preference/technician_name/confirmation/info_complete(bool)/unrelated(bool)/missing_info(list[str])`，带类型约束与字段 description（保留 start_time 的标准格式与相对时间换算说明）

## 2. 改造 TaskClassifier（消灭字符串解析）

- [x] 2.1 用 `self.llm.with_structured_output(TaskCategory)` 构建 chain，替换 `prompt | llm`
- [x] 2.2 `classify_task` 内部 `await chain.ainvoke(...)` 取 `result.category` 返回 `str`；**删除** `strip().lower()` + `valid_categories` 白名单兜底
- [x] 2.3 保留异常降级：LLM 调用异常时记录结构化日志并返回 `other`（不抛出）
- [x] 2.4 `classify_task` 对外签名（参数/返回 str）保持不变

## 3. 改造 InputParser（结构化抽取 + 去名义流式）

- [x] 3.1 用 `self.llm.with_structured_output(AppointmentSlots)` 构建 chain；保留 `time_config` 注入的当前时间到 prompt
- [x] 3.2 新增 `async def extract(user_input, chat_history) -> AppointmentSlots`，写入 chat_history（Human/AI）行为保留
- [x] 3.3 `parse_data` 改为返回 `AppointmentSlots.model_dump()` 的 dict 视图（兼容 `data.get(...)`）；**删除** `json.loads` + 兜底 dict 的脆弱链路
- [x] 3.4 移除/改造逐 token 的 `parse_stream`（调用方本就缓冲后整体解析，无 UX 回归）
- [x] 3.5 抽取异常降级：返回 `info_complete=false` 的默认 `AppointmentSlots` 并记录结构化日志

## 4. 调整调用点

- [x] 4.1 `agents/appointment_agent.py:run_stream` 第 1 步改为 `slots = await extract(...)`；`data = slots.model_dump()`，下游 `data.get("unrelated")` 等保持可用
- [x] 4.2 同步更新 `tests/test_appointment_agent.py` 中以 `parse_stream` 取 `ai_content` 的两处为新调用形态（仅测试，不补 phantom）

## 5. 验证（闸门 2）

- [x] 5.1 `uv run pytest`：维持 `21 passed / 9 xfailed / 0 failed`，不退化
- [x] 5.2 `uv run python evals/run_evals.py`：格式错误率→0，端到端意图准确率 ≥ 基线 95%（≥19/20 同口径）；记录是否修复基线错例「约个李师傅，他这周六有空吗」
- [x] 5.3 确认未触碰 `services/`/`db/`/`config/model_provider.py`/RAG
- [x] 5.4 `openspec validate phase-1-structured-output` 通过
- [x] 5.5 在 tasks 末尾追加「验证结果（一次性运行记录）」：pytest 计数、评估准确率、错例处理结论

## 6. 验证结果（一次性运行记录）

- **`uv run pytest`（全量）**：`21 passed, 9 xfailed, 0 failed`，退出码 0（119s）。与 Phase 0 基线一致，无退化。classification 测试走离线 `FakeChatModel`（已为其补 `with_structured_output` 支持）；appointment 测试走真实 LLM，结构化抽取正确得到 `project=按摩 / gender=女 / start_time 含 14:00 / unrelated`。
- **`uv run python evals/run_evals.py`**：意图准确率 **19/20 (95.0%)**，等于 Phase 0 基线（appointment 5/6 · query 5/5 · pay 3/3 · statistics 3/3 · other 3/3）。**格式错误率→0**：不再出现解析失败/兜底 `other`（修复前一版因 classifier prompt 残留"只返回类别英文名"等输出格式指令，与结构化输出冲突，导致 13/20=65%；清理 prompt 后恢复 95%）。
- **基线错例**：「约个李师傅，他这周六有空吗」仍判为 `query`（期望 `appointment`）——与基线同一条，属语义边界（"有空吗"被当查询），非格式问题；修复留待后续（stretch goal，非本 Phase 硬指标）。
- **改动范围**：仅 `agents/task_classification/{task_classifier,schemas}.py`、`agents/appointment/{input_parser,schemas}.py`、`agents/appointment_agent.py`（调用点）、`tests/{conftest,test_appointment_agent}.py`。**未触碰** `services/`/`db/`/`config/model_provider.py`/RAG。
- **残留**：langchain 结构化输出内部 `parsed` 字段的 Pydantic 序列化 `UserWarning`（良性，非失败）；SQLAlchemy Deprecation 警告（预存，与本 change 无关）。
