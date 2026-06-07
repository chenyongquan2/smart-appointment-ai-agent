## Context

`uv run pytest` 当前 21 failed / 9 passed。诊断后失败分两类,**均非真实回归**:

1. **async 未配置(7 个,`test_task_classification_agent.py`)**:项目未装 `pytest-asyncio`,`@pytest.mark.asyncio` 是未知 mark;且这些 "RealWorkflow" 测试实例化真实 agent、经 `config.model_provider.create_chat_model` 取 LLM 并真实调用,需 key 且非确定。
2. **phantom 测试(14 个,`test_user_behavior_agent.py`)**:断言了一套**从未实现的 API**——`agent.recommendation_generator` / `insight_provider` / `behavior_processor` 属性不存在;`behavior_recorder.record_behavior(dict)` 与真实签名 `(action_type, action_data, ...)` 不符;`get_recent_behavior` / `pattern_analyzer.identify_behavior_patterns` / `preference_manager.save_preferences` 等方法均不存在。这批测试从未绿过,不反映真实行为。

约束:`agents/` 层即将被重构替换(见 harness-refactor-plan),因此**不值得为 phantom API 写实现**;`services/`/`db/`/`config/` 是保留资产,不动。

## Goals / Non-Goals

**Goals:**
- `uv run pytest` 在无 key、离线下退出码 0,`failed=0`。
- async 测试真正执行;classification 测试确定、离线可复现。
- phantom 测试以带理由的 `xfail` 隔离,可追溯。

**Non-Goals:**
- 不重构 `agents/` 业务逻辑、不实现任何 phantom API。
- 不改 `services/`/`db/`/`config/` 运行时代码。
- 不追求 user_behavior 层的测试覆盖(留给重构期的 `harness/` 新测试)。
- 不引入 `evals/` 变更(那是另一条线)。

## Decisions

### D1:用 `pytest-asyncio` + `asyncio_mode = "auto"`
在 `[dependency-groups].dev` 加 `pytest-asyncio`,`[tool.pytest.ini_options]` 设 `asyncio_mode = "auto"`。
- **为何 auto 而非 strict**:测试已有 `@pytest.mark.asyncio` 标记,auto 模式对二者都兼容、改动最小;strict 要求每个 async 测试显式标记,无额外收益。
- **备选**:`anyio` —— 否决,项目无 anyio 依赖,pytest-asyncio 是 LangChain 生态默认。

### D2:在 `tests/conftest.py` 注入假 LLM,patch 点 `config.model_provider.create_chat_model`
所有 agent 都从 `create_chat_model` 取 LLM,这是唯一统一缝。conftest 提供一个 fixture(对 classification 测试 autouse 或显式引用),`monkeypatch` 该工厂返回一个 **FakeChatModel**:
- 兼容 LangChain Runnable(支持 `prompt | llm` 组合与 `await chain.ainvoke(...)`),返回 `AIMessage`。
- 内容按输入启发式给确定结果:含"天气/你好/谢谢/吃"等 → 分类返回 `other`(驱动标准拒绝串);含"按摩/推拿/价格/服务" → `query`;含"预约" → `appointment`。下游 handler 收到假内容时返回非空、非错误串即可满足现有宽松断言(`len>0`、不以"处理任务时发生错误"开头)。
- **为何 patch 工厂而非每个 `self.llm`**:一处生效、覆盖 classifier 与被路由的 appointment/consultant agent,避免逐类打桩。
- **备选**:`responses`/录制真实调用回放 —— 否决,过重且仍偶发联网。

### D3:user_behavior phantom 测试用类级 `@pytest.mark.xfail(reason=..., strict=False)`
对断言不存在 API 的测试(类或方法级)加 `xfail`,reason 指明"断言未实现的 API;agents/ 待重构,不补 phantom 实现(见 change fix-preexisting-test-debt)"。
- **为何 xfail 而非删除**:保留为"重构期待补的行为清单"线索,且若将来真实现了会以 `xpassed` 提示回收;`strict=False` 避免 xpass 变红。
- **为何不实现 API**:与 Non-Goals 一致,违背"不重写 agents/"红线。
- **备选**:删除文件 —— 否决,丢失线索且显得"假装覆盖过"。

## Risks / Trade-offs

- **假 LLM 偏离真实路由** → 断言本就宽松(非空、非错误、固定拒绝串),假内容只需触发对应分支;不追求语义保真。
- **`asyncio_mode=auto` 影响未来同步测试** → auto 仅对 async 函数生效,同步测试不受影响。
- **xfail 掩盖未来真实退化** → 仅用于已确认的 phantom 测试,逐条带 reason;真实测试不挂 xfail。
- **patch 点将来重构改名** → `create_chat_model` 属保留的 `config/` 资产,稳定;若重构 harness 改了缝,届时随新测试一并更新。

## Migration Plan

1. 加依赖与配置 → `uv sync`。
2. 写 conftest 假 LLM,classification 测试接入。
3. user_behavior phantom 测试加 xfail。
4. `uv run pytest` 验证退出码 0、`failed=0`,确认 xfail 计数与清单吻合。
- **回滚**:本 change 仅动测试基础设施,`git revert` 即可,无运行时影响。

## Open Questions

- 无。两道取舍(phantom→xfail、LLM→mock)已与发起人确认。
