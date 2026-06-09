## Why

Phase 0 的验收要求"跑通现有 `tests/` 并记录黄金样本",但当前 `uv run pytest` 是 **21 failed / 9 passed**。这些失败不是真实回归,而是两类预存债:async 测试缺运行配置、以及一批断言了从未实现 API 的"愿望测试"。重构 `agents/` → `harness/` 之前若没有可信的安全网,任何改动都无法区分"我改坏了"和"它本来就红"。

## What Changes

- **加 async 测试支持**:在 dev 依赖组引入 `pytest-asyncio` 并在 `pyproject.toml` 配 `asyncio_mode`,使 `@pytest.mark.asyncio` 标记的测试能真正被收集执行(当前是未知 mark)。
- **classification 测试改为 mock LLM**:`test_task_classification_agent.py` 的 7 个 async 测试当前真调 LLM(需 API key、非确定)。通过统一 patch 点 `config.model_provider.create_chat_model` 注入假 LLM,使其确定、无需 key、可离线跑。
- **隔离 user_behavior 的 14 个 phantom 测试**:`test_user_behavior_agent.py` 断言了一套从未实现的 API(`recommendation_generator`/`insight_provider`/`behavior_processor` 等属性根本不存在,`get_recent_behavior`/`save_preferences` 等方法也不存在)。这些测试从未绿过、不反映真实行为,且 `agents/` 层即将被重构替换。以 `xfail`(strict=False)隔离并附说明,而非实现 phantom API。
- **范围红线**:**不重构 `agents/` 业务逻辑、不实现任何 phantom API、不改 `services/`/`db/`**。仅动测试基础设施(依赖/配置/mock)与测试文件本身的隔离标记。

## Capabilities

### New Capabilities
- `test-safety-net`: 让 `uv run pytest` 在无 API key、离线条件下确定性地全绿(或全 pass + 受控 xfail),作为重构 `agents/` 前的黄金样本与回归防线。

### Modified Capabilities
<!-- 无 spec 级行为变更:eval-harness 能力不受影响 -->

## Impact

- **依赖**:`pyproject.toml` `[dependency-groups].dev` 新增 `pytest-asyncio`;`[tool.pytest.ini_options]` 新增 `asyncio_mode`。
- **测试文件**:`tests/test_task_classification_agent.py`(引入 mock 夹具)、`tests/test_user_behavior_agent.py`(加 xfail 标记);可能新增 `tests/conftest.py`(共享假 LLM 夹具)。
- **不影响**:`agents/`、`services/`、`db/`、`config/`、`evals/` 的运行时代码均不改。
- **验收**:`uv run pytest` 退出码 0,无 failed;受控 xfail 有清晰理由可追溯。
