## 1. 脚手架与工具基类

- [x] 1.1 新建 `harness/__init__.py`、`harness/tools/__init__.py`。
- [x] 1.2 在 `harness/tools/base.py` 定义 `Tool`（name/description/args_schema/handler）抽象，handler 签名为 `async def handler(args: BaseModel) -> Any`。
- [x] 1.3 在 `harness/tools/schemas.py` 定义各工具入参 Pydantic 模型（复用 Phase 1 `AppointmentSlots` 约定的时间/时长格式）。
- [x] 1.4 增加时间字符串→`datetime` 的小 helper（含 duration 推导 end_time），供工具 handler 复用。

## 2. 实现 5 个工具（薄封装 services/）

- [x] 2.1 `harness/tools/knowledge.py`：`search_knowledge(query, top_k)` → `await KnowledgeService.search`，返回结构化结果。
- [x] 2.2 `harness/tools/technician.py`：`find_technician(start_time, duration, project, preference, gender, technician_name)` → 复用 `TechnicianFinder`（指定技师优先，否则按条件过滤+查可用）。
- [x] 2.3 `harness/tools/availability.py`：`check_availability(technician_id, start_time, end_time)` → `AppointmentService.is_technician_available`，返回布尔。
- [x] 2.4 `harness/tools/appointment.py`：`create_appointment(...)` → `AppointmentService.save_appointment`，返回保存结果。
- [x] 2.5 `harness/tools/preference.py`：`get_user_preferences(user_id)` → `UserBehaviorService.get_user_preferences` / `analyze_user_patterns`。

## 3. ToolRegistry

- [x] 3.1 `harness/tools/registry.py`：`ToolRegistry` 支持 `register`（重名报错）、`get`、`dispatch(name, raw_args)`（先用 args_schema 校验再调 handler，未知名报错）。
- [x] 3.2 实现 `to_openai_schema()`：基于各工具 `args_schema.model_json_schema()` 导出 `{type:"function", function:{name,description,parameters}}` 列表。
- [x] 3.3 实现 `to_anthropic_schema()`：导出 `{name,description,input_schema}` 列表。
- [x] 3.4 提供 `build_default_registry()`：注册全部 5 个工具，便于复用与测试。

## 4. 测试

- [x] 4.1 `tests/test_harness_tools.py`：每个工具——合法参数转交对应 service（mock service 断言调用与返回）、非法参数触发 Pydantic 校验且 service 不被调用。
- [x] 4.2 `tests/test_tool_registry.py`：注册/重名报错/按名 dispatch/未知名报错；`to_openai_schema` 与 `to_anthropic_schema` 结构正确且字段源于 Pydantic 模型。
- [x] 4.3 确认依赖方向：`services/` 不 import `harness/`（grep 校验）。

## 5. 验证与归档

- [x] 5.1 跑 `uv run pytest`，全绿（成功静默、只报失败）。
- [ ] 5.2 若 `evals/` 有运行器，跑 `uv run python evals/run_evals.py`，对照基线无回归。
- [x] 5.3 核对验收标准：每个工具可单测；ToolRegistry 能导出 Anthropic/OpenAI 格式 tools schema。
- [ ] 5.4 用户确认后 `/opsx:archive` 归档并更新 specs。
