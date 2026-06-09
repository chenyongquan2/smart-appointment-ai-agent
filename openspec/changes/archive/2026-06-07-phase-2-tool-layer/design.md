## Context

Phase 1 已用 Pydantic v2 + function calling 消灭了分类/抽取的字符串解析。Phase 2 要把 `services/` 的能力暴露成 LLM 可调用工具，为 Phase 3 的 agent loop 提供"动作"层。当前 `services/` 接口已确认（部分 async、部分同步）：

- `KnowledgeService.search(query, top_k=3, category=None)` —— **async**，返回 `List[Dict]`。
- `TechnicianService` / `AppointmentService`：`get_technician_by_name`、`get_all_technicians`、`get_technicians_by_gender`、`is_technician_available(technician_id, start_time: datetime, end_time: datetime)`、`save_appointment(technician_id, start_time, end_time, appointment_history, session_id)` —— **同步**。
- `TechnicianFinder`（`agents/appointment/technician_finder.py`）含 `find_specific_technician` / `find_similar_available_technician` 等，封装了"指定技师 / 找相似可用技师"的查找逻辑。
- `UserBehaviorService.get_user_preferences(user_id)` / `analyze_user_patterns(user_id)` —— 同步。

`harness/` 目录尚不存在，本 Phase 全新建。

## Goals / Non-Goals

**Goals:**
- 建立 `harness/tools/`：一个工具一个文件，四要素（name/description/args schema/handler）。
- 5 个薄封装工具，参数经 Pydantic 校验后转交 service。
- `ToolRegistry`：注册、按名分发（带 schema 校验）、导出 Anthropic + OpenAI tools schema。
- 每个工具与 registry 可独立单测（不依赖真实 DB 时用 service 层 mock）。

**Non-Goals:**
- 不实现 agent loop / TAO 编排（Phase 3）。
- 不接线进 `agents/` 现有路由或 API（Phase 3 才替换）。
- 不重写任何 `services/` 业务逻辑；不改 `db/`、`config/model_provider.py`、RAG。
- 不做护栏的超时/重试/权限（Phase 5），本 Phase 仅做 schema 入参校验。

## Decisions

1. **工具抽象用统一基类/协议**：在 `harness/tools/base.py` 定义 `Tool`（dataclass 或基类），字段 `name: str`、`description: str`、`args_schema: type[BaseModel]`、`handler: Callable`。每个工具文件导出一个 `Tool` 实例（或构造函数）。理由：显式、可被 registry 统一处理。
2. **统一 handler 签名**：`handler(args: BaseModel) -> Any`，接收已校验的 args 模型实例，返回结构化结果（dict / Pydantic / 基础类型）。registry 负责"原始 dict → schema 校验 → 传入 handler"。
3. **async 一致性**：因 `KnowledgeService.search` 是 async，所有 handler 统一定义为 `async def`，同步 service 直接调用即可。`registry.dispatch` 为 `async`。理由：与 Phase 3 的 async agent loop 对齐，避免混合 sync/async。
4. **时间入参用字符串 + 解析**：工具 args schema 的时间字段沿用 Phase 1 `AppointmentSlots` 约定（`YYYY-MM-DD HH:MM` 字符串），handler 内部转 `datetime` 再传 service。`duration` 用于推导 `end_time`。理由：与既有抽取层一致，便于 loop 直接喂槽位。
5. **find_technician 复用 TechnicianFinder**：handler 内部调用 `TechnicianFinder` 的查找逻辑（指定技师优先，否则按 gender/preference 过滤 + 查可用），不在工具里重写匹配规则。
6. **schema 导出基于 `model_json_schema()`**：用 Pydantic v2 `model_json_schema()` 生成参数 JSON Schema，再各自包成 OpenAI（`{type:"function", function:{name,description,parameters}}`）与 Anthropic（`{name,description,input_schema}`）外壳。理由：单一真相源是 Pydantic 模型，两格式自动同步。
7. **依赖方向**：`harness/tools/` → `services/`（及为复用查找逻辑而 import `agents/appointment/technician_finder.py`）。services 不反向 import harness。注意 `find_technician` 依赖 `agents/` 是临时的；Phase 3 迁移后可下沉。

## Risks / Trade-offs

- **import `agents/appointment/technician_finder`**：让 harness 暂时依赖 agents 层（横向）。权衡：避免重写匹配逻辑（违反"薄封装"原则）。标注为临时，Phase 3 处理。
- **全 async**：同步 service 包进 async handler 略显啰嗦，但换来与 loop 的一致性，避免后期返工。
- **DB 依赖的单测**：service 直连 SQLite。单测优先 mock service 层（验证"工具正确转交参数 + 校验 schema + 导出格式"），少量集成测试可走真实 DB（已有测试基线）。
- **时间解析重复**：工具层与抽取层都做字符串→datetime。可抽一个小 helper，但不引入新依赖。
