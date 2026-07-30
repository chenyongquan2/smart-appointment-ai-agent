# 修复向量化调用无超时且阻塞事件循环

## Why

向量化调用会**无限期挂起并冻结整个事件循环**，已实测造成 evals 跑批死锁两次；在生产上会让飞书长连接的收包与心跳一起停摆，机器人静默失联且不报任何错。

两个叠加的缺陷：

1. **超时是假的**：`services/text_embedding.py` 的 `embed_input` 声明了 `timeout: int = 600` 却**从未使用**——签名里的谎言。而 `config/model_provider.py` 的 `create_embedding_model()` 创建 `OpenAIEmbeddings` 时也没传任何超时（实测 `timeout` 未设置、`request_timeout` 为 `None`），于是落到 openai 客户端默认的 600 秒。签名里那个幽灵 `600` 正是它。
2. **同步调用跑在事件循环上**：`embed_query` 是同步阻塞调用，却被 `KnowledgeService` 的 **6 处 `async` 方法**直接调用。一旦 HTTP 请求挂住，就占住整个事件循环——连 `asyncio.wait_for` 的定时器回调都跑不了，所以任何外层超时都救不了它。

实测证据（2026-07-29，两次可复现）：进程 CPU 8 秒内增长 0.0 秒（完全空转）、2 个 `ESTABLISHED` 到 :443 挂着不动 + 9 个 `CLOSE_WAIT`、日志静默十余分钟；同时用独立脚本量 LLM 延迟正常（1.4–2.5s），排除外部 API 整体变慢。

**为什么现在做**：飞书接入（已归档的 `feishu-channel-integration`）让长连接与 Web 共用同一个事件循环，把这个缺陷的后果从「评估跑批卡住」升级为「机器人整体失去响应且不报错」——最难归因的一类生产故障。它同时也让 evals 门禁持续不可用，阻塞后续所有需要门禁把关的变更。

## What Changes

- **超时落到实处**：`create_embedding_model()` 支持并默认施加请求超时，取值来自新增环境变量 `EMBEDDING_TIMEOUT_SECONDS`（缺省 **20 秒**——向量化本该是秒级操作，600 秒等于没有上限）。`embed_input` 的 `timeout` 参数真正透传，不再是装饰。
- **新增异步路径**：新增 `aembed_input()`，走 LangChain 的原生 `aembed_query`（已确认 `OpenAIEmbeddings` 提供该方法）。原生异步意味着调用**可被取消**，于是事件循环不再被占住，外层的工具超时也终于能生效。
- **改造调用点**：`KnowledgeService` 的 6 处 `async` 方法改为 `await aembed_input(...)`。同步版 `embed_input` **保留**，供 `find_best_match_indices` 这类同步调用点使用（它们不在事件循环的关键路径上）。
- **测试**：注入一个永久挂起的 fake embedding，断言调用在超时内以错误收场而非无限期挂住；并断言同步路径行为不变。

**非目标**：不改 RAG 的检索逻辑、不动 SQLite+FAISS 基础、不重写 `KnowledgeService` 的任何业务规则。不修「`text-embedding-3-small` 在当前网关不可用」那个独立的配置问题——本变更修的是「慢/挂的请求必须被掐断」，与「模型是否可用」正交：模型换好之后，无超时 + 同步阻塞的缺陷依然会在任何一次慢请求上复现。

## Capabilities

### New Capabilities

（无——沿用既有 `guardrails`。）

### Modified Capabilities

- `guardrails`: 新增需求「外部调用超时与非阻塞」——嵌入等外部 I/O 调用 MUST 有可配置的超时上限；在 `async` 上下文中 MUST NOT 执行同步阻塞 I/O（否则占住事件循环，使一切外层超时失效）。该 capability 已owns「LLM 调用超时与重试」与「副作用工具不被重试」，本需求是同一族约束的补齐。

## Impact

- **代码**：`config/model_provider.py`（`create_embedding_model` 加超时）、`services/text_embedding.py`（`timeout` 真正生效 + 新增 `aembed_input`）、`services/knowledge_service.py`（6 处调用点改 await 异步版）。
- **配置**：`.env` / `.env.example` 新增 `EMBEDDING_TIMEOUT_SECONDS`（缺省 20）。
- **保留资产的处置**：`services/` 与 `config/model_provider.py` 在 `openspec/project.md` 的「不要动」清单上。本变更**只加超时与异步路径，不重写业务逻辑**——这属于清单所禁的「重写」之外的最小加固；若不加，该清单保护的恰恰是一个会冻死整个服务的实现。
- **连带收益**：evals 门禁重新可跑（当前因本缺陷持续不可用，见已归档 change 的 tasks 4.2 标注）；`Tool.timeout` 对 `search_knowledge` 从「声明了但无效」变为真正生效。
- **验证**：`uv run pytest` 全绿；新增挂起注入测试；修复后重跑 `uv run python evals/run_evals.py --samples 3` 应能跑完（这本身就是本变更是否奏效的端到端证据）。
