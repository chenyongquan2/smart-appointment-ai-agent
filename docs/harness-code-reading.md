# 读懂 Harness 源码：按 7 站逐站精读（每站自包含）

> 📍 本文属于 harness 学习系列（**第 4 步 · 读源码**）。总览见 [harness-index.md](./harness-index.md)。
>
> 前三步学的是「harness 是什么 / 高手怎么做 / 本项目怎么规划」；这一步动手**读 `harness/` 的真实代码**。配套：[harness-refactor-plan.md](./harness-refactor-plan.md)（每站对应哪个 Phase）。
>
> **本文按「站」组织**：每一站把「解决什么 / 读哪些文件 / 关键代码 / 设计要点 / 断点调试 / 小实验」全放在一起，自包含、可逐站展开学习。读完一站勾掉它的 `[ ]` 再进下一站。

---

## 📖 怎么用这份导读

整个 `harness/` 才约 **2000 行**，每个文件基本 **<120 行**，而且**每个模块都有对应测试**——这是它最大的学习优势：**测试就是用法说明书**。

三条铁律：

1. **测试是入口**。每个 `harness/X.py` 都配了 `tests/test_X.py`。先读测试看「它被怎么调用、输入输出长什么样」，再回头读实现。
2. **顺数据流读，别按字母序**。一条用户消息进来 → loop → 工具 → 记忆 → 护栏 → trace → 子 Agent → 端到端，按这个顺序走一遍。
3. **对照 plan 读**。每站标注了对应 Phase，读代码时回看 plan 里那段「目标/验收」，理解**为什么这么设计**而不只是写了什么。

**每站的固定学习动作**：①读「关键代码」建立印象 → ②读「设计要点」理解为什么 → ③按「断点调试指引」单步跑一遍，把文字变成肌肉记忆。

---

## 🛠️ 调试环境准备（全站共用，先读一次）

读代码配合**单步调试**最快建立直觉。本项目对调试很友好——`tests/test_agent_loop.py` 用**离线 fake LLM**（`ScriptedChatModel`，按预设脚本返回 `AIMessage`），**不用配 API key、不触网、可重复**，是学循环的首选入口。

仓库已有 [.vscode/launch.json](../.vscode/launch.json)，含三个配置：

| 配置 | 用途 |
|------|------|
| **Pytest: 调试测试** | 离线确定性调试（学循环首选）。学单个测试时：测试资源管理器右键单个测试 → Debug Test，或把 `args` 临时改成 `["tests/test_agent_loop.py::test_single_tool_then_reply", "-s"]` |
| **FastAPI: 调试整个应用 (uvicorn)** | 调真服务。已正确**不加 `--reload`**（reload 会 fork 子进程导致断点不命中） |
| **Python: 调试当前文件** | 调某个独立模块 |

操作：打断点 → `F5` 选配置 → `F10` 跳过（不进函数）/ `F11` 进入（步入）/ `Shift+F11` 跳出 / `F5` 继续到下个断点。想单步进 LangChain 内部，确认 `justMyCode: false`（已默认）。

> ⚠️ 三个坑：① 调真服务别用 `--reload`；② Python 解释器必须选 `.venv`（uv 装的），否则 `ModuleNotFoundError`；③ 调真服务需 `.env` 里配好 `LLM_*` / `AZURE_OPENAI_*`。

> 🔑 **调试黄金法则**：先用最少的断点看懂主节奏，再逐步加点深入。学循环只需在 [agent_loop.py:146](../harness/runtime/agent_loop.py#L146) 和 [:156](../harness/runtime/agent_loop.py#L156) 打两个点，反复 F5，盯住三件事——**messages 变长 → 有没有 tool_calls → 最终出 [REPLY]**。看懂这个节奏，就懂了整个 harness。

---

## 🗺️ 一图看清调用关系

```
用户消息
  │
  ▼
[chat_handler]  ──按 session_id 取──▶  Session (runtime/session.py)
  │                                        │
  ▼                                        ├─ short_term / summary / long_term (memory/)
AgentLoop (runtime/agent_loop.py)  ◀───组装上下文 + system_prompt
  │   每轮：assemble → LLM(tools) → dispatch → observe
  │
  ├─▶ ToolRegistry (tools/registry.py) ──分发──▶ 各 tool ──薄封装──▶ services/
  │
  ├─▶ Guardrails (guardrails/)  retry / budget / permission  包在 loop 和工具外
  │
  ├─▶ Tracer (observability/)  on_tool_call / on_observation  埋点
  │
  └─▶ delegate 工具 (subagents/) ──派生──▶ 子 Agent（各自独立上下文）
```

---

# 第 1 站 · 心脏：Agent Loop（Phase 3）⭐ 最重要

整个 harness 的主循环，其它一切都被它调用。**最该花时间的一站。**

## 1.1 这站解决什么

取代「LLM 分类一次 + if/else 硬路由」的老做法，改成让**绑定了工具 schema 的 LLM 自主决定每一步**——这就是 TAO（Thought→Action→Observation）循环。

## 1.2 读哪些文件

- [ ] 实现 [agent_loop.py](../harness/runtime/agent_loop.py)（~217 行）
- [ ] 测试 [test_agent_loop.py](../tests/test_agent_loop.py)
- 对照 [plan 第 105–126 行](./harness-refactor-plan.md) 的 TAO 伪代码看。

## 1.3 关键代码：一轮循环的 6 块

`run()` 是个 **async generator**，把 TAO 伪代码变成真代码。看 [agent_loop.py:98-185](../harness/runtime/agent_loop.py#L98)：

```python
async def run(self, user_input, session_id=None, history=None, system_suffix=None):
    # ── ① 组装上下文 ───────────────────────────────────────────────
    # 一次请求的「初始上下文」= 系统提示 + 历史 + 本轮用户输入。
    system_content = self.system_prompt
    if system_suffix:                          # system_suffix 常是「长期偏好提示」，拼到系统提示末尾
        system_content = f"{system_content}\n\n{system_suffix}"
    messages = [SystemMessage(content=system_content)]    # messages = 喂给 LLM 的对话数组（会越滚越长）
    if history:
        messages.extend(history)               # history 由 chat_handler 传入 → loop 自身不存任何状态
    messages.append(HumanMessage(content=user_input))     # 末尾放本轮用户消息

    spin = SpinDetector(self.repeat_limit)     # 打转检测器：跨步累计「连续相同的工具调用」次数
    root = self._tracer.start_span("agent_loop.run", ...)  # 整次 run 开一个根 span（一条 trace）
    try:
        # ── ② 开循环 + 预算闸门 ─────────────────────────────────────
        for _step in range(self.max_steps):    # 用 range 而非 while True：天然有硬上限，绝不死循环
            # 发 LLM 前先估算上下文体量，超预算就不再花钱调用，直接优雅收尾
            if self.max_tokens is not None and estimate_tokens(messages) > self.max_tokens:
                yield f"[REPLY]{_FALLBACK_REPLY}"
                return
            step = self._tracer.start_span("step", parent=root)   # 每轮一个子 span，挂在 root 下
            try:
                # ── ③ LLM 调用（Thought）：带超时 + 重试护栏 ──────────
                try:
                    ai = await self._guarded_invoke(messages)     # 返回一条 AIMessage（模型这轮的输出）
                except GuardrailExhausted:      # 重试都失败 → 不让异常冒泡，给兜底回复后结束
                    yield f"[REPLY]{_FALLBACK_REPLY}"; return
                messages.append(ai)             # 把模型这轮输出也加回上下文（下一轮模型能看到自己说过啥）

                # ── ④ 分叉点（整个 harness 最重要的 if）──────────────
                tool_calls = ai.tool_calls or []        # 模型这轮想调的工具列表，可能为空
                if not tool_calls:              # 空 = 模型不再需要工具 → 这就是最终回复，结束循环
                    yield f"[REPLY]{_content_text(ai.content)}"
                    return
                if spin.check(tool_calls):      # 连续 N 轮调完全相同的工具+参数 → 判定卡死，提前逃生
                    yield f"[REPLY]{_FALLBACK_REPLY}"; return

                # ── ⑤ 执行工具（Action）+ 把结果喂回（Observation）──
                for call in tool_calls:         # 同一轮可能有多个调用，逐个执行、全部喂回
                    result = await self._dispatch(call)            # 调具体工具，拿到结果（或错误字符串）
                    messages.append(            # 结果包成 ToolMessage 加回上下文
                        ToolMessage(content=str(result),
                                    tool_call_id=call["id"])       # id 把「这条结果」对应回「哪次调用」
                    )
                # ☝️ 这里没有 return：for 跑完会回到 for _step 顶部，进入下一轮（带着新结果再问模型）
            finally:
                self._tracer.end_span(step)     # 无论这轮怎么结束，都关闭子 span
        # ── ⑥ 兜底：跑满 max_steps 仍没出最终回复 ──────────────────
        yield f"[REPLY]{_FALLBACK_REPLY}"
    finally:
        self._tracer.end_span(root)             # 关闭根 span（导出整条 trace）
```

`messages` 列表像**滚雪球**：每轮加上「模型输出 + 工具结果」越来越长，直到模型看够信息、吐出不带 tool_calls 的最终回复。

逐块对照表：

| 块 | 行 | 干什么 | 关键点 |
|---|---|---|---|
| ① 组装上下文 | 119–126 | `[System(+suffix)] + history + Human` | context engineering 落点；loop **自身无状态** |
| ② 开循环+护栏 | 136–142 | `range(max_steps)` + token 预算 + tracer span | 非 `while True`，有硬上限 |
| ③ LLM 调用 | 144–153 | `_guarded_invoke` → `messages.append(ai)` | 带超时+重试；耗尽降级 |
| ④ 分叉点 | 155–165 | 无 tool_calls → 出 `[REPLY]`；有 → 过打转检测 | **整个 harness 最重要的 if** |
| ⑤ 执行+喂回 | 167–178 | 逐个 `_dispatch` → 包 `ToolMessage` append | `tool_call_id` 把结果对应回调用 |
| ⑥ 兜底+收尾 | 182–185 | 撞 `max_steps` → 兜底；`finally` 关 span | 绝不无限循环 |

## 1.4 设计要点：两个可靠性内核（故意不对称）

```python
async def _guarded_invoke(self, messages):   # 守 LLM 调用（agent_loop.py:187）
    # LLM 调用是「只读、幂等」的——重发一次不产生副作用，所以可以安全重试。
    return await guarded_invoke(              # ↓ 包一层超时 + 指数退避重试（实现见第 4 站）
        lambda: self.llm.ainvoke(messages),
        timeout=..., max_attempts=...,
    )

async def _dispatch(self, call):              # 守工具调用（agent_loop.py:197）
    # 工具调用「可能有副作用」（如写库下单）——绝不重试，只做错误隔离。
    try:
        return await self.registry.dispatch(call["name"], call.get("args") or {})
    except Exception as exc:                  # 注意：捕获「全部」异常，不只瞬时异常
        # 把异常吞成一句错误字符串返回；它会被当成正常工具结果喂回模型，
        # 让模型下一轮「看到」失败并自行补救——而不是让整个循环崩掉。
        return f"工具执行失败（{call.get('name', '?')}）：{exc}"
```

| | `_guarded_invoke`（LLM） | `_dispatch`（工具） |
|---|---|---|
| 失败处理 | **重试**（指数退避） | **不重试**，捕获返回错误字符串 |
| 异常范围 | 只瞬时异常（超时/连接） | `except Exception`（全部） |
| 目的 | 扛网络抖动 | 错误隔离 + 回灌自愈 |

**为什么不对称**：LLM 调用只读幂等，可重试；工具调用有副作用——`create_appointment` 重试一次就重复下单。`_dispatch` 把异常吞成字符串当正常结果喂回，模型下一轮「看到」失败、自行换参/换工具/告知用户 → **单工具崩溃不崩循环**。

工具执行的三道防线（从外到内）：

```
_dispatch (agent_loop.py:197)            ← ① 错误隔离：任何异常 → 错误字符串回灌
  └─ registry.dispatch (registry.py:56)  ← ② 权限闸门：dangerous 工具先审批，拒则返回结构化拒绝
       └─ tool.run (base.py:40)          ← ③ 参数校验：Pydantic args_schema 不合法即拒
            └─ handler → services/        ← 真正业务（薄封装）
```

> 🔑 一句话记住整份代码的可靠性哲学：**幂等的可重试（LLM），有副作用的不可重试、只隔离（工具）**。`[REPLY]` 前缀则是与 chat_handler 的约定，后者据此择出回复文本回写历史。

**带着问题读的答案**：
- 什么时候结束？→ [:156](../harness/runtime/agent_loop.py#L156) 模型不再返回 `tool_calls`。
- 怎么防失控？→ 三道闸：`max_steps`（[:136](../harness/runtime/agent_loop.py#L136)）、token 预算（[:138](../harness/runtime/agent_loop.py#L138)）、打转检测（[:162](../harness/runtime/agent_loop.py#L162)）。

## 1.5 🐞 断点调试指引

**用「Pytest: 调试测试」跑 [`test_single_tool_then_reply`](../tests/test_agent_loop.py#L126)**（脚本化了「调一次工具 → 回复」两步，最适合看完整一轮）。

| 断点 | 位置 | F5 到达后看什么 |
|---|---|---|
| 1 | [agent_loop.py:146](../harness/runtime/agent_loop.py#L146) `ai = await self._guarded_invoke(messages)` | **第一次命中**：看 `messages`——此刻只有 `[SystemMessage, HumanMessage("查一下")]`。F10 越过本行，看 `ai.tool_calls` 是 `[echo(...)]` |
| 2 | [agent_loop.py:156](../harness/runtime/agent_loop.py#L156) `if not tool_calls:` | **分叉点**：第一轮 `tool_calls` 非空 → 不进 if，继续往下 |
| 3 | [agent_loop.py:173](../harness/runtime/agent_loop.py#L173) `result = await self._dispatch(call)` | 看 `call["name"]=="echo"`、`call["args"]`。**按 F11 步入** `_dispatch` → 再 F11 进 `registry.dispatch` → 再 F11 进 `tool.run` → 看 Pydantic 校验后调 handler |
| 4 | [agent_loop.py:176](../harness/runtime/agent_loop.py#L176) `messages.append(ToolMessage(...))` | **关键**：看工具结果 `echo<hi>` 被包成 `ToolMessage` 喂回。此刻 `messages` 已有 4 条 |
| 5 | 回到断点 1（第二次命中） | `messages` 变长到 4 条；F10 后 `ai.tool_calls` 为空 → 走 [:158](../harness/runtime/agent_loop.py#L158) 出 `[REPLY]已为您查询完成。` |

**推荐首次动线**：只在断点 1 和 2 打点 → F5 → 观察「messages 变长 → 是否有 tool_calls → 最终出 [REPLY]」反复两轮的节奏。

**破坏性小实验**（理解护栏最快的方式）：
- 跑 [`test_max_steps_fallback`](../tests/test_agent_loop.py#L196)（脚本永远返回工具调用），在 [:136](../harness/runtime/agent_loop.py#L136) 打点数 `_step` 到 3 次后走 [:183](../harness/runtime/agent_loop.py#L183) 兜底——看 `max_steps` 怎么救命。
- 把任意工具 handler 临时改成 `raise`，在 [:201](../harness/runtime/agent_loop.py#L201) 打点，看异常如何变成回灌字符串（参考 [`test_tool_failure_is_fed_back_not_crash`](../tests/test_agent_loop.py#L217)）。

---

# 第 2 站 · 手脚：工具层（Phase 1 + 2）

loop 调用的就是工具。看「能力如何被包装成模型可调用的东西」。

## 2.1 这站解决什么

把「能力」包装成 LLM 可调用的东西，且工具内部**只是 services/ 的薄封装**，不重写业务。

## 2.2 读哪些文件

- [ ] [tools/base.py](../harness/tools/base.py) — 工具基类（name / description / schema / handler）
- [ ] [tools/registry.py](../harness/tools/registry.py) — 注册 + 生成 LLM schema + 按名分发
- [ ] [tools/schemas.py](../harness/tools/schemas.py) — Pydantic 模型（Phase 1 结构化输出的成果）
- [ ] 任挑一个具体工具：[tools/knowledge.py](../harness/tools/knowledge.py) 或 [tools/appointment.py](../harness/tools/appointment.py)
- [ ] 测试 [test_tool_registry.py](../tests/test_tool_registry.py) + [test_harness_tools.py](../tests/test_harness_tools.py)

## 2.3 关键代码：工具四要素

[`Tool`](../harness/tools/base.py#L19) 是个 frozen dataclass：

```python
@dataclass(frozen=True)                       # frozen=True：工具一旦定义不可变，可安全共享/复用
class Tool:
    name: str                                 # 唯一名（snake_case）：模型用它指名调用、registry 用它分发
    description: str                          # 面向模型的「说明书」——模型靠它判断「何时该调用我」
    args_schema: type[BaseModel]              # 入参的 Pydantic 模型「类」（注意不是实例）
    handler: Callable[[BaseModel], Awaitable[Any]]   # 真正干活的 async 函数，收「已校验」的参数对象
    dangerous: bool = False                   # True=有副作用（如写库下单），分发前要先过权限闸门

    async def run(self, raw_args: dict) -> Any:
        # raw_args 是模型给的「原始 dict」，可能缺字段 / 类型不对
        validated = self.args_schema(**raw_args)   # ① Pydantic 校验+转型；不合法直接抛 ValidationError
        return await self.handler(validated)        # ② 把「干净的」参数对象交给 handler 执行
```

**一个具体工具**（[`search_knowledge`](../harness/tools/knowledge.py#L21)）——体会「薄封装」：

```python
async def _handler(args: SearchKnowledgeArgs) -> list[dict]:   # args 已是校验过的对象，直接 .query 取用
    # 延迟 import：模块加载时不拉起重型 service/索引，等真正被调用才初始化（加快启动、省内存）
    from services.knowledge_service import KnowledgeService
    service = KnowledgeService()
    if not getattr(service, "initialized", False):   # 仅首次调用时初始化（懒加载）
        await service.initialize()
    # 直接把参数转交给既有 service——工具层不写任何检索/业务逻辑
    return await service.search(args.query, top_k=args.top_k, category=args.category)
    # ☝️「薄封装」的精髓：校验交给 Pydantic、业务交给 services/，工具只做「转接」
```

## 2.4 设计要点：单一真相源

Pydantic 模型如何变成 LLM 能读的 schema？看 [`registry.to_openai_schema()`](../harness/tools/registry.py#L74)：

```python
def to_openai_schema(self) -> list[dict]:     # 把所有已注册工具导出成 OpenAI function-calling 格式
    return [
        {"type": "function", "function": {
            "name": tool.name,                 # 复用工具的 name
            "description": tool.description,   # 复用工具的 description（同一份文字，喂给模型）
            "parameters": tool.args_schema.model_json_schema(),  # ☜ Pydantic 一行生成 JSON Schema
        }}
        for tool in self._tools.values()       # 遍历注册表里的每个工具
    ]
    # 结果会喂给 llm.bind_tools(...)，模型据此知道「有哪些工具、各要什么参数」
```

**这就是「单一真相源」**：Pydantic 模型既用于运行时校验，又用于生成给 LLM 的 schema，两者永远一致、不会漂移。[`schemas.py`](../harness/tools/schemas.py) 里每个 `Field(description=...)` 都会进 schema，直接告诉模型每个参数什么意思。

**分发链** [`registry.dispatch()`](../harness/tools/registry.py#L56)：`get(name)` 找工具 → 危险工具先过权限闸门 → `tool.run(raw_args)`。重名注册直接报错拒绝覆盖（[:31](../harness/tools/registry.py#L31)）。另有 [`subset()`](../harness/tools/registry.py#L44) 能切出工具子集给子 Agent 用（第 6 站会用到）。

**带着问题读的答案**：
- 工具如何把 Pydantic 变 LLM schema？→ `model_json_schema()`。
- 为什么只是薄封装？→ 业务、可靠性、领域逻辑都在 `services/`，工具只做「参数校验 + 转交」，职责单一、易测、不重复维护。

## 2.5 🐞 断点调试指引

跑 [`test_tool_registry.py`](../tests/test_tool_registry.py)，或在第 1 站动线里步入工具：
- 在 [base.py:42](../harness/tools/base.py#L42) `validated = self.args_schema(**raw_args)` 打点——看 raw dict 怎么变成校验后的 Pydantic 实例。**故意传个非法参数**（如 `top_k=999` 超过 `le=20`），看 Pydantic 在这里抛 `ValidationError`，再回第 1 站看它如何被 `_dispatch` 吞成错误字符串回灌。
- 在 [registry.py:72](../harness/tools/registry.py#L72) `return await tool.run(raw_args)` 打点——这是工具分发的统一出口。

---

# 第 3 站 · 上下文与记忆（Phase 4）

loop 每轮要「组装上下文」，这部分决定模型看到什么。

## 3.1 这站解决什么

决定模型看到什么；并取代 Phase 3 的「全局单例 + 全局 session_id」。

## 3.2 读哪些文件

- [ ] [runtime/session.py](../harness/runtime/session.py) — 按 session_id 隔离的状态
- [ ] [memory/short_term.py](../harness/memory/short_term.py) — 短期对话窗口
- [ ] [memory/summary.py](../harness/memory/summary.py) — 超窗压缩为摘要（目前为占位 stub）
- [ ] [memory/long_term.py](../harness/memory/long_term.py) — 跨会话用户偏好
- [ ] [runtime/system_prompt.py](../harness/runtime/system_prompt.py) — 角色 + 可用工具说明
- [ ] 测试 [test_memory.py](../tests/test_memory.py) + [test_session_store_restart.py](../tests/test_session_store_restart.py)

## 3.3 关键代码：会话隔离

[`SessionStore`](../harness/runtime/session.py#L41) 核心是一个 dict：

```python
class SessionStore:
    def __init__(self, repo=None):
        self._repo = repo                      # 持久层（SQLite repository）；None 时纯内存（测试用）
        self._sessions: Dict[str, SessionState] = {}   # 内存缓存：session_id → 该会话的「独立」状态

    def get_or_create(self, session_id, user_id=None) -> SessionState:
        state = self._sessions.get(session_id)         # 先查内存（热会话，命中即返回）
        if state is None:                              # 内存没有（冷启动 / 重启后第一次访问）
            state = SessionState(                      # 才去建一个
                session_id=session_id,
                history=self._load_history(session_id),   # ☜ 从 DB 懒加载历史 → 进程重启也能恢复
            )
            self._sessions[session_id] = state         # 放进内存缓存，下次直接命中
        return state

    def append_turn(self, session_id, role, content):  # 每说一句（user 或 assistant）就记一条
        state = self.get_or_create(session_id)
        state.history.append(Turn(role=role, content=content))   # ① 写内存（本次请求立即可见）
        if self._repo is not None:
            self._repo.append_turn(session_id, role, content)    # ② 同步写 DB（进程重启后还在）
```

## 3.4 设计要点：分层记忆（按升级关系理解）

- **短期** [`ShortTermMemory.to_messages`](../harness/memory/short_term.py#L29)：只取最近 N 轮，转成 LangChain 消息：
  ```python
  recent = history[-self.window_turns:]      # 只取最近 N 条；更早的「不进上下文」但仍留在 DB
  # 再逐条转成 LangChain 消息类型：user → HumanMessage，assistant → AIMessage（未知 role 跳过）
  ```
- **摘要** [`summary.py`](../harness/memory/summary.py)：⚠️ **目前是占位 stub**。[`NoOpSummary.summarize`](../harness/memory/summary.py#L39) 永远返回空串。读它主要看它定义的 `Protocol` 接口契约——「超窗本应压缩成摘要」是设计意图，真正的 LLM 压缩留待后续 Phase。
- **长期** [`LongTermMemory.build_preference_hint`](../harness/memory/long_term.py#L39)：跨会话读用户偏好，组装成一句中文提示。关键设计——失败不影响主流程：
  ```python
  try:
      prefs = self._repo.get_user_preferences(user_id)   # 跨会话读该用户的历史偏好
  except Exception as exc:                    # 读失败（DB 抖动等）也不能拖垮对话
      logger.warning(...); return ""           # 吞掉异常、返回空串 → 没有偏好提示，但主流程照常
  # 拿到偏好后会拼成一句中文提示（如「该用户偏好女技师」），作为 system_suffix 注入
  ```

**系统提示** [`build_system_prompt`](../harness/runtime/system_prompt.py#L34)：基线角色提示 + **动态注入**已注册工具说明（从每个 `tool.description` 拼，[:47-49](../harness/runtime/system_prompt.py#L47)）。又是单一真相源——工具说明只写一次。

**带着问题读的答案**：
- 两个 session 为什么不串号？→ 它们是 `_sessions` dict 里两个不同 key 对应的两个独立 `SessionState` 对象，内存上互不可见。
- 重启后怎么恢复？→ `get_or_create` 内存 miss 时 `_load_history` 从 SQLite 读回（看 restart 测试）。

## 3.5 🐞 断点调试指引

这站靠「对照测试」最有效（多数记忆逻辑是同步纯函数，比调真服务快）：
- 跑 [`test_session_store_restart.py`](../tests/test_session_store_restart.py)：在 [session.py:57](../harness/runtime/session.py#L57) `_load_history(session_id)` 打点——构造「新建一个 store、用同一 session_id 取」，看历史从 repo 被读回来。
- 跑 [`test_memory.py`](../tests/test_memory.py)：在 [short_term.py:34](../harness/memory/short_term.py#L34) 打点，把 `window_turns` 临时改小（如 2），看长历史被裁到只剩最近 2 条。
- 在第 7 站真服务动线里，在 [chat_handler.py:80](../api/chat_handler.py#L80) 打点，看 `history_msgs` 和 `preference_hint` 如何被取出注入 loop。

---

# 第 4 站 · 护栏：可靠性（Phase 5）

看 harness 怎么在出错时不崩。

## 4.1 这站解决什么

让 harness 出错时不崩。三个文件各管一类失败。

## 4.2 读哪些文件

- [ ] [guardrails/retry.py](../harness/guardrails/retry.py) — 超时 / 指数退避
- [ ] [guardrails/budget.py](../harness/guardrails/budget.py) — token 预算 + 打转检测
- [ ] [guardrails/permission.py](../harness/guardrails/permission.py) — 危险操作权限
- [ ] 测试三件套 `test_guardrails_retry / budget / permission` + [test_agent_loop_guardrails.py](../tests/test_agent_loop_guardrails.py)

## 4.3 关键代码

**重试** [`guarded_invoke`](../harness/guardrails/retry.py#L40)：

```python
# 只有「瞬时」异常才值得重试：超时、连接断。鉴权错/参数错重试多少次都一样，应直接冒泡。
RETRYABLE_EXCEPTIONS = (asyncio.TimeoutError, TimeoutError, ConnectionError)

async def guarded_invoke(call, *, timeout=30, max_attempts=3, base_delay=0.5, sleep=None):
    sleep_fn = sleep or asyncio.sleep          # sleep 可注入：测试传一个「不真睡」的函数 → 秒级跑完
    for attempt in range(max_attempts):        # 最多尝试 max_attempts 次（含首次）
        try:
            return await asyncio.wait_for(call(), timeout=timeout)   # 单次调用超时即算本次失败
        except RETRYABLE_EXCEPTIONS as exc:    # 只接住可重试的那几类异常（其它直接冒泡）
            last_exc = exc
            if attempt + 1 < max_attempts:     # 还有下次机会才睡；最后一次失败不必再睡
                await sleep_fn(base_delay * (2 ** attempt))   # 退避翻倍 0.5→1→2s，避免雪崩式重试
    # 循环跑完还没 return = 所有尝试都失败 → 抛专门异常，由 loop 捕获后降级
    raise GuardrailExhausted(...) from last_exc
```

**打转检测** [`SpinDetector`](../harness/guardrails/budget.py#L63)：

```python
def _signature(tool_calls):                    # 把「这一轮的工具调用」压成一个可比较的指纹
    return tuple(sorted(
        # 每个调用取 (工具名, 参数JSON)；sort_keys=True 让 {a,b} 与 {b,a} 算同一指纹
        (str(call.get("name","")), json.dumps(call.get("args") or {}, sort_keys=True))
        for call in tool_calls))

class SpinDetector:
    def check(self, tool_calls) -> bool:       # 每轮调一次，返回「是否已卡死打转」
        sig = _signature(tool_calls)
        if sig == self._last_sig:              # 和上一轮指纹一样 → 计数 +1
            self._count += 1
        else:                                  # 指纹变了 → 重新从 1 计数
            self._last_sig = sig; self._count = 1
        return self._count >= self._repeat_limit    # 连续相同达到上限（默认 3）→ 判定打转
```

**权限** [`permission.py`](../harness/guardrails/permission.py)：策略是个可调用对象 `Callable[[Tool, dict], Decision]`，默认 [`allow_all`](../harness/guardrails/permission.py#L42) 放行一切（向后兼容）。危险工具被拒时，[`registry.dispatch`](../harness/tools/registry.py#L64) 返回结构化拒绝：

```python
if tool.dangerous:                             # 只有危险工具（写库类）才走权限判定
    decision = self._permission(tool, raw_args)    # 把(工具, 入参)交给策略，得到放行/拒绝
    if not decision.allow:                     # 被拒：不执行 handler
        # 返回一个「结构化拒绝」结果，它会沿错误回灌路径喂回模型（模型据此换策略或告知用户）
        return {"success": False, "denied": True, "reason": decision.reason}
# 放行（或非危险工具）才会往下真正执行 tool.run(...)
```

## 4.4 设计要点

- **token 估算**（[`estimate_tokens`](../harness/guardrails/budget.py#L40)）：字符数/4 的粗估，不引入 tiktoken、跨 provider 适用，只为「是否超上限」的判断，不求精确计费。
- **护栏怎么「包在」外面**：retry 包 LLM 调用（[`_guarded_invoke`](../harness/runtime/agent_loop.py#L187)）；permission 包在 `registry.dispatch` 里；budget 在 loop 每步开头检查。三道护栏分别在不同层切入，互不耦合（回第 1 站的「三道防线」图）。

**带着问题读的答案**：
- 单工具异常 loop 为什么不崩？→ 回第 1 站 `_dispatch` 的错误隔离 + 回灌自愈。
- 护栏怎么包在 loop/工具外？→ 见上面「护栏怎么包在外面」。

## 4.5 🐞 断点调试指引

- **看重试**：跑 [`test_guardrails_retry.py`](../tests/test_guardrails_retry.py)，在 [retry.py:68](../harness/guardrails/retry.py#L68) `asyncio.wait_for` 打点，看 `attempt` 递增、退避时长翻倍（注入的 no-op sleep 让它不真睡）。
- **看打转**：跑 [`test_guardrails_budget.py`](../tests/test_guardrails_budget.py)，在 [budget.py:81](../harness/guardrails/budget.py#L81) `if sig == self._last_sig` 打点，看连续相同调用时 `_count` 累加到 `repeat_limit`。
- **看权限拦截**：跑 [`test_agent_loop_guardrails.py`](../tests/test_agent_loop_guardrails.py)，在 [registry.py:64](../harness/tools/registry.py#L64) `if tool.dangerous:` 打点，看危险工具被拒后返回结构化拒绝、**handler 根本没执行**。
- **破坏性实验**：给 loop 传一个很小的 `max_tokens`（如 10），在 [agent_loop.py:138](../harness/runtime/agent_loop.py#L138) 打点，看预算闸门怎么在发 LLM 调用前就拦截。

---

# 第 5 站 · 可观测性（Phase 6）

## 5.1 这站解决什么

把循环内部的 thought/tool_call/observation 记录下来，能打日志也能发 OTel。

## 5.2 读哪些文件

- [ ] [observability/span.py](../harness/observability/span.py) — 一次 trace 的最小单元
- [ ] [observability/tracer.py](../harness/observability/tracer.py) — on_tool_call / on_observation 埋点
- [ ] exporter：[logging_exporter.py](../harness/observability/logging_exporter.py) / [otel_exporter.py](../harness/observability/otel_exporter.py)
- [ ] 测试 [test_observability_tracer.py](../tests/test_observability_tracer.py) + [test_observability_otel.py](../tests/test_observability_otel.py)

## 5.3 关键代码

**最小单元** [`Span`](../harness/observability/span.py#L28)：

```python
@dataclass
class Span:                 # 一次 trace 里的一个「跨度」（一段可计时的工作）
    trace_id: str          # 同一次请求的所有 span 共享同一个 → 用它把整条链路串起来检索
    span_id: str           # 本 span 自己的唯一 id
    parent_id: Optional[str]   # 指向父 span；root span 没有父 → None。父子关系我们「手动」维护
    name: str              # span 名，如 "agent_loop.run" / "step"
    start: float; end: Optional[float] = None   # 起止时刻（注入的时钟）→ 相减即得 latency
    attributes: dict = field(default_factory=dict)   # 可检索标签：session_id / tokens / 工具名 …
    events: list[SpanEvent] = field(default_factory=list)  # 按时间顺序记的事件流：thought/tool_call/observation
```

**埋点器** [`Tracer`](../harness/observability/tracer.py#L38)：

```python
def start_span(self, name, parent=None, attributes=None) -> Span:
    # 有父 → 继承父的 trace_id（同一条 trace）；无父 → 自己就是 root，生成一个新 trace_id
    trace_id = parent.trace_id if parent is not None else self._id_factory()
    return Span(trace_id=trace_id,
                span_id=self._id_factory(),                  # 本 span 自己的新 id
                parent_id=parent.span_id if parent else None,  # 记住父是谁 → 树不会断
                ...)

def end_span(self, span):
    span.end = self._clock()                   # 记结束时刻（这样 latency 才算得出来）
    try:
        self._exporter.export(span)            # 交给后端导出（打日志 / 发 OTel）
    except Exception:                          # 导出失败也绝不能影响业务
        pass                                   # 吞掉异常：可观测是「旁路」，挂了不许拖垮主流程
```

`clock` 和 `id_factory` 可注入（[:51-52](../harness/observability/tracer.py#L51)）——测试注入计数器，得到**确定性可断言**的 id 和 latency。

## 5.4 设计要点：三个巧思

1. **不依赖 OTel 隐式 context**：父子关系靠显式 `parent_id`（[span.py:8-9](../harness/observability/span.py#L8)），所以在手写 async 循环里不会「断树」。
2. **NoopTracer 实现向后兼容**：[`NoopTracer`](../harness/observability/tracer.py#L107) 复用 `Tracer` 的 span 构造（让调用方能拿到 span 做父子传参），但 `end_span` 不导出、事件方法覆盖为 no-op。loop 未注入 tracer 时用它（[agent_loop.py:92](../harness/runtime/agent_loop.py#L92)），**接入前后行为完全一致**。
3. **exporter 抽象**：`Tracer` 只认 `SpanExporter.export(span)` 接口，logging 和 otel 是两个实现 → 同一份 trace 既能打日志又能发 OTel，换后端不动 loop。

**loop 在哪些点埋点**（回第 1 站）：root span [:131](../harness/runtime/agent_loop.py#L131)、每步 child [:142](../harness/runtime/agent_loop.py#L142)、thought [:152](../harness/runtime/agent_loop.py#L152)、tool_call [:170](../harness/runtime/agent_loop.py#L170)、observation [:175](../harness/runtime/agent_loop.py#L175)。

## 5.5 🐞 断点调试指引

- 跑 [`test_observability_tracer.py`](../tests/test_observability_tracer.py)，在 [tracer.py:65](../harness/observability/tracer.py#L65) `trace_id = parent.trace_id if ...` 打点——看 root span 生成新 trace_id、child span 继承同一 trace_id（验证「不断树」）。
- 在 [tracer.py:79](../harness/observability/tracer.py#L79) `self._exporter.export(span)` 打点，看一个 span 结束时被导出，`span.events` 里按序记着 thought/tool_call/observation。
- **对照实验**：跑第 1 站任意测试（不注入 tracer），在 [agent_loop.py:152](../harness/runtime/agent_loop.py#L152) 打点 F11 步入——会发现进了 `NoopTracer.add_thought`（直接 `pass`），印证「未注入时零副作用」。

---

# 第 6 站 · 进阶：子 Agent / Skills（Phase 7）

## 6.1 这站解决什么

把任务交给专用子 Agent，且**不靠硬编码路由**——由主 Agent 在 TAO 循环里自主决定。

## 6.2 读哪些文件

- [ ] [subagents/base.py](../harness/subagents/base.py) — 子 Agent 基类
- [ ] [subagents/delegate.py](../harness/subagents/delegate.py) — **关键：`delegate` 本身就是一个工具**
- [ ] [subagents/registry.py](../harness/subagents/registry.py) + 三个具体子 Agent（appointment / consultant / user_behavior）
- [ ] [skills/base.py](../harness/skills/base.py) + [skills/registry.py](../harness/skills/registry.py)
- [ ] 测试 [test_subagents.py](../tests/test_subagents.py) + [test_skills.py](../tests/test_skills.py) + [test_system_prompt_subagents.py](../tests/test_system_prompt_subagents.py)

## 6.3 关键代码：delegate 本身就是一个工具

**最关键的认知**：[`delegate`](../harness/subagents/delegate.py) 是一个普通 `Tool`，所以「派生子 Agent」=第 1 站里的一次普通工具调用。

```python
def build_delegate_tool(llm, full_registry, subagent_registry) -> Tool:
    # 构造期：把已注册的子 Agent 渲染进 description，让主模型知道「有哪些专员可派、各管什么」
    options = "；".join(f"{a.name}（{a.description}）" for a in subagent_registry.all())
    description = f"把一个子任务委派给某个专用子 Agent……可派生的子 Agent：{options}。"

    async def _handler(args: DelegateArgs) -> dict:   # 模型调 delegate 时传 {subagent, task}
        agent = subagent_registry.get(args.subagent)  # 按名找到目标子 Agent
        result = await agent.run(args.task, full_registry, llm)   # 让它在「独立上下文」里跑完整任务
        # 只把「最终结论」打包回主 Agent——子 Agent 的中间步骤不外泄
        return {"success": True, "subagent": args.subagent, "result": result}

    # ☝️ delegate 和普通工具长得一模一样（四要素）→ 主循环用同一套 tool-calling 调它，无需特殊分支
    return Tool(name="delegate", description=description, args_schema=DelegateArgs, handler=_handler)
```

**子 Agent 怎么跑** [`SubAgent.run`](../harness/subagents/base.py#L43)：

```python
async def run(self, task, full_registry, llm, session_id=None) -> str:
    subset = full_registry.subset(list(self.tool_names))   # ① 从全量工具里切出「我能用的那几个」
    # ② 复用主循环 AgentLoop！只是换了「专用系统提示」+「工具子集」——不重写任何循环逻辑
    loop = AgentLoop(llm=llm, registry=subset, system_prompt=self.system_prompt)
    reply = ""
    async for token in loop.run(task, session_id=session_id):   # ③ 跑一遍 mini TAO（独立的 messages）
        if token.startswith("[REPLY]"):       # 用和主循环一样的 [REPLY] 约定捞出最终回复
            reply = token[len("[REPLY]"):]
    return reply                               # 只把最终文本交回 delegate handler（中间步骤不外泄）
```

**怎么搭这套**（[chat_handler.py:35-47](../api/chat_handler.py#L35)）——**主 registry 只含 delegate**：

```python
_full_registry = build_default_registry()          # 全量领域工具（查知识/找技师/查档期/下单/查偏好）
_subagents = build_default_subagent_registry()      # 三个专员：预约 / 咨询 / 行为分析
_delegate_tool = build_delegate_tool(_llm, _full_registry, _subagents)  # 把它们包成一个 delegate 工具

_main_registry = ToolRegistry()
_main_registry.register(_delegate_tool)             # ☜ 主 Agent 手里「只有」delegate 这一个工具
# → 主 Agent 的唯一职责是「决定派给哪个专员」，领域工具一律由子 Agent 去执行（关注点分离）
```

## 6.4 设计要点

- **复用而非重写**：子 Agent 复用 `AgentLoop`（连带护栏/tracer/错误隔离全继承），只换 system_prompt 和工具子集。
- **上下文隔离**：子 Agent 在独立的 `messages` 里跑，主 Agent 只通过 delegate 的返回 dict 拿到最终结论——经第 1 站喂回路径变成主 Agent 的 ToolMessage。
- **Skills 按需加载**：[`Skill.matches`](../harness/skills/base.py#L35) 用**确定性关键词匹配**（不引入向量检索，保证离线可测），[`SkillRegistry.load_for(task)`](../harness/skills/registry.py#L34) 返回所有相关 skill。

**带着问题读的答案**：
- 主 Agent 如何「自主决定」派给谁？→ system prompt 里列了子 Agent 清单（[`build_system_prompt`](../harness/runtime/system_prompt.py#L51) 渲染），模型在 TAO 循环里调 delegate 工具并指定 subagent，**不是 if/else**。
- 结果怎么汇总回主 Agent？→ delegate handler 返回 `{"result": ...}`，经喂回路径成为主 Agent 的 ToolMessage；子 Agent 中间步骤不外泄。

## 6.5 🐞 断点调试指引

跑 [`test_subagents.py`](../tests/test_subagents.py)：
- 在 [delegate.py:65](../harness/subagents/delegate.py#L65) `agent = subagent_registry.get(args.subagent)` 打点——看主 Agent 选了哪个子 Agent、`args.task` 是什么。
- F11 步入 [base.py:61](../harness/subagents/base.py#L61) `subset = full_registry.subset(...)`——看子 Agent 只拿到自己那几个工具。
- 继续步入子 Agent 的 `loop.run`——你会**回到第 1 站的同一段 `AgentLoop.run` 代码**（复用！），但这次 `system_prompt` 和工具集都不同。这一刻最能体会「子 Agent = 换装的主循环」。
- 跑 [`test_skills.py`](../tests/test_skills.py)，在 [base.py:38](../harness/skills/base.py#L38) `return any(kw in task for kw in keywords)` 打点，看关键词命中判定。

---

# 第 7 站 · 闭环：端到端 + 评估（Phase 0 + 6）

## 7.1 这站解决什么

把前面所有东西串起来，并度量这套 harness 好不好。**读完它就懂整体了。**

## 7.2 读哪些文件

- [ ] [test_chat_handler_e2e.py](../tests/test_chat_handler_e2e.py) — 把前面所有东西串起来的全流程
- [ ] [evals/run_evals.py](../evals/run_evals.py) + [evals/metrics.py](../evals/metrics.py) + [evals/cases.jsonl](../evals/cases.jsonl)
- [ ] [evals/README.md](../evals/README.md)

## 7.3 关键代码：一条消息的完整路径

[`ProcessUserInput_stream`](../api/chat_handler.py#L58)：

```python
async def ProcessUserInput_stream(user_input, state=None, context=None, session_id=None):
    sid = session_id or str(uuid.uuid4())          # 没传 session_id 就新开一个会话
    session = _session_store.get_or_create(sid)    # ① 取该会话的独立状态（第 3 站）

    # ② 组装记忆：短期历史（最近 N 轮）+ 长期偏好（跨会话）
    history_msgs = _short_term.to_messages(session.history)
    preference_hint = _long_term.build_preference_hint(session.user_id)
    _session_store.append_turn(sid, "user", user_input)   # ③ 先把本轮用户输入记入历史

    reply_text = ""
    async for token in _agent_loop.run(            # ④ 驱动主循环（第 1 站；内部用到 2/4/5/6 站）
        user_input,
        session_id=sid,
        history=history_msgs,                      # 历史作为上下文注入
        system_suffix=preference_hint,             # 偏好作为系统提示补充注入
    ):
        if token.startswith("[REPLY]"):            # 从流式产出里挑出最终回复那条
            reply_text = token[len("[REPLY]"):]
        yield token                                # 边产出边转发给前端（流式）
    if reply_text:
        _session_store.append_turn(sid, "assistant", reply_text)  # ⑤ 回写回复 → 下一轮能接上
```

## 7.4 关键代码：评估怎么打分

[`metrics.py`](../evals/metrics.py) 是**纯函数、不触网**，故可离线确定性单测。核心设计——**缺数据显式标 N/A，不伪造分母**：

```python
def tool_call_correctness(results) -> Metric:
    # 只挑「既有期望工具、又抓到了实际工具」的用例参与统计——分母不掺没法评的样本
    eligible = [r for r in results if r.expected_tools is not None and r.actual_tools is not None]
    if not eligible:                            # 一个可评的都没有
        return Metric("工具调用正确率", na=True,   # 就如实标 N/A，并写明原因（不伪造 0%/100%）
                      note="本次运行未捕获实际工具调用（需端到端执行 AgentLoop）")
    # set(...) 比较：只看「调了哪些工具」，不计顺序与重复次数
    correct = sum(1 for r in eligible if set(r.actual_tools) == set(r.expected_tools))
    return Metric("工具调用正确率", value=correct/len(eligible), ...)   # 正确数 / 可评样本数
```

[`run_evals.py`](../evals/run_evals.py) 负责跑真实分类器把结果填进 `EvalResult`，再交给 metrics 汇总；还有「缺 API key 优雅降级」（[:155-163](../evals/run_evals.py#L155)）。

## 7.5 设计要点

- 四个指标：意图准确率、工具调用正确率、槽位完整率、端到端延迟。
- 度量与执行解耦：`metrics.py` 只管算（纯函数易测），`run_evals.py` 只管跑（接真 provider）。

**带着问题读的答案**：
- 一条消息经过哪些文件？→ chat_handler → session/short_term/long_term → agent_loop → registry → tool → services（危险工具还经 permission；全程经 tracer）。
- 评估怎么定义期望并打分？→ `cases.jsonl` 写 `expected_intent`/`expected_tools`/`expected_slots`，metrics 用集合比较打分，缺数据标 N/A。

## 7.6 🐞 断点调试指引

- **真服务端到端**（需 `.env` 配好 key）：用「FastAPI: 调试整个应用」配置，在 [chat_handler.py:77](../api/chat_handler.py#L77) 打点 → 前端发一条消息 → 单步走完整条链路：会话隔离 → 记忆注入 → loop → 回写。这是把 7 站串起来的总演练。
- **不要 key 的话**：跑 [`test_chat_handler_e2e.py`](../tests/test_chat_handler_e2e.py)，在 [chat_handler.py:87](../api/chat_handler.py#L87) `async for token in _agent_loop.run(...)` 打点 F11 步入——直接进第 1 站的循环。
- **看评估**：`uv run python evals/run_evals.py --limit 5`，或在 [metrics.py:60](../evals/metrics.py#L60) 打点跑 `test_evals_metrics`，看 N/A 判定逻辑。
- **看真实 trace**：`uv run pytest tests/test_chat_handler_e2e.py -s`，观察 thought/tool_call/observation 输出。

---

## 🧭 贯穿全程的 4 条设计哲学（最该带走的）

读完你会发现这些原则反复出现，比任何单个文件都重要：

1. **单一真相源**：Pydantic 模型 → 同时供校验和 LLM schema；工具 description → 同时供模型和系统提示。改一处，处处一致。
2. **幂等可重试，有副作用只隔离**：LLM 重试、工具绝不重试。这是整份代码的可靠性哲学。
3. **向后兼容靠「退化默认」**：`NoopTracer` / `allow_all` / `NoOpSummary` 让新能力可选接入、不破坏既有行为与测试。
4. **可注入依赖换确定性测试**：LLM、`sleep`、`clock`、`id_factory` 全可注入 → 测试离线、不触网、可断言。**测试就是最好的用法说明书。**

---

## 📅 推荐学习节奏

| 阶段 | 做什么 | 时间占比 |
|---|---|---|
| 1 | **第 1 站**：读代码 + 按动线单步调试 `test_single_tool_then_reply`，看懂「滚雪球 → 分叉 → 喂回」 | 40% |
| 2 | **第 2–6 站**：每站「读关键代码 + 答问题 + 跑一个断点/实验」快速过 | 各 ~10% |
| 3 | **第 7 站**：端到端串起来 + 凭记忆画一张「消息从进来到返回经过哪些文件」的图——画得出 = 真懂了 | 收口 |

> 不要平均用力——loop 是心脏，其余都是它的附属。全部 7 站读完，你就完整走过了 plan 里 Phase 0–7 的所有产出。
