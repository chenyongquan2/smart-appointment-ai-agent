## Why

技师专长相似度匹配在 `async` 上下文里执行**同步阻塞 HTTP**，会冻住整个事件循环——同进程内所有协程（含飞书长连接的收包与心跳）一并停摆。

这与归档 change `fix-embedding-timeout-blocking`（2026-07-30）修的是**同一个缺陷**，当时只修了知识库那条路径、技师这条漏了；`remove-local-rag` 删掉知识库后，它成了项目里**唯一**仍在违反 `guardrails`「async 上下文 MUST NOT 执行同步阻塞 I/O」的地方。

调用链（两条，都在 async 上下文）：

| # | 入口 | 到达点 |
|---|---|---|
| 1 | `harness/tools/technician.py:18` `async def _handler` → `:39` 同步调 `find_technician_with_thought` | 活路径，`find_technician` 工具 |
| 2 | `agents/appointment/appointment_processor.py:188` `async def handle_complete_appointment` → `:226` 同步调同一方法 | 遗留路径，`/api/appointment` 端点 |

两条都会经 `technician_finder.py:242` `filter_technicians_by_preference`（**只要带力度偏好就必走**，评估集里预约类多数用例都带）或 `:98` `find_similar_available_technician`（指定技师不可用时走），落到 `services/text_embedding.py:20`：

```python
candidate_embs = [embed_input(c) for c in candidates]   # 每个候选一次同步阻塞 HTTP
```

加上查询本身共 **N+1 次串行阻塞请求**，每次上限 20 秒（`EMBEDDING_TIMEOUT_SECONDS`）。`embed_input` 自己的 docstring 就写明"在 async 上下文里请用 `aembed_input`，否则会占住整个事件循环"——而这里正是从协程里调用的。

## What Changes

- **新增 `services/text_embedding.afind_best_match_indices`**：异步版相似度排序，用 `aembed_input` + `asyncio.gather` **并发**取全部候选向量。除了解阻塞，还把 N+1 次串行请求压成一轮并发——延迟从 `(N+1) × RTT` 降到约 `1 × RTT`。
- **`TechnicianFinder` 的三个方法改为 async**：`filter_technicians_by_preference`、`find_similar_available_technician`、`find_technician_with_thought`。不涉及 embedding 的方法（`parse_time_and_duration`、`filter_technicians_by_gender`、`find_available_technician`、`find_specific_technician`）保持同步——它们只做本地 SQLite 查询与字符串处理，不属本次要解的问题。
- **两个调用方改为 `await`**：`harness/tools/technician.py:39`、`agents/appointment/appointment_processor.py:226`。
- **删除同步版 `find_best_match_indices`**：改造后零调用方，留着就是死代码（`embed_input` 本身保留，见 design D3）。
- **补回归测试**：沿用 `test_embedding_timeout.py` 的"心跳不停"范式（注入永不返回的 fake embeddings + `@pytest.mark.timeout` 走线程/信号——事件循环被冻住时，基于 asyncio 的超时救不了自己）。这条测试正是 `remove-local-rag` 里随 `KnowledgeService` 删掉、当时明确记下"技师路径尚缺"的那一条。

## Capabilities

### New Capabilities
- 无。本变更是让既有实现**符合既有需求**（conformance fix），不引入新能力。

### Modified Capabilities
- `guardrails`: 「外部调用超时与非阻塞」的两条约束不变，为其补一条**可执行的场景**——技师专长相似度匹配在 async 上下文中 MUST NOT 冻住事件循环，且多候选向量化 SHALL 并发发起。原需求只在抽象层面禁止同步阻塞，没有任何场景锚定到具体调用点，这正是技师这条路径能长期违规而无人察觉的原因。

## Impact

**代码**：`services/text_embedding.py`（+1 async 函数，−1 同步函数）、`agents/appointment/technician_finder.py`（3 个方法改 async）、`harness/tools/technician.py`（1 行 await）、`agents/appointment/appointment_processor.py`（1 行 await）。

**测试**：新增 `tests/test_technician_matching_nonblocking.py`（心跳不停 + 并发验证 + 排序结果不变）；`tests/test_harness_tools.py` 的 `FakeFinder` 打桩需把被替换的方法改成 async。

**行为**：匹配结果**不变**（同样的向量、同样的相似度排序），变的只是"怎么发请求"。故评估指标应当不动——`find_technician` 仍被调用、仍返回同一位技师。

**收益**：`remove-local-rag` 只让 `query` 类与 embedding 网关解耦；本变更补上 `appointment` 类的另一半——网关慢或挂时，不再冻住整个服务（仍会失败，但失败得干净、可取消、不牵连他人）。
