## 1. async 测试基础设施

- [x] 1.1 `pyproject.toml` `[dependency-groups].dev` 加 `pytest-asyncio`,`[tool.pytest.ini_options]` 加 `asyncio_mode = "auto"`
- [x] 1.2 `uv sync` 安装依赖
- [x] 1.3 冒烟:运行任一 async 测试,确认不再有 `PytestUnknownMarkWarning`、测试体真正执行

## 2. classification 测试 mock LLM

- [x] 2.1 在 `tests/conftest.py` 实现 `FakeChatModel`(兼容 `prompt | llm` 组合与 `await ainvoke`,返回 `AIMessage`),内容按输入启发式给确定分类/响应
- [x] 2.2 提供 fixture,用 `monkeypatch` 替换 `config.model_provider.create_chat_model`,在 `test_task_classification_agent.py` 接入(autouse 或显式)
- [x] 2.3 跑 `test_task_classification_agent.py` 全部用例:确定通过、无真实网络调用、无需 key
- [x] 2.4 核对宽松断言仍满足(返回非空字符串、不以"处理任务时发生错误"开头、无关输入返回标准拒绝串)

## 3. 隔离 user_behavior phantom 测试

- [x] 3.1 逐一确认 `test_user_behavior_agent.py` 中断言不存在 API 的测试(对照 `agents/user_behavior_agent.py` 真实属性/方法)
- [x] 3.2 对这些测试加 `@pytest.mark.xfail(reason="断言未实现的 API;agents/ 待重构,不补 phantom 实现(change: fix-preexisting-test-debt)", strict=False)`(能整类则类级,否则方法级)
- [x] 3.3 若有个别测试其实对得上真实 API,则保留为正常测试,不挂 xfail

## 3b. appointment 测试签名错位(实现期新发现,非 proposal 原列)

- [x] 3b.1 `test_appointment_agent.py::test_should_handle_incomplete_info_gracefully` 调 `handle_incomplete_info(data)` 与真实签名 `(data, appointment_history)` 错位 —— 同类预存债。补传已存在的 `agent.appointment_history`,使其离线确定性通过(引导问题来自 `message_builder` 模板,非 LLM,含"时间")。不改 `agents/` 源码。

## 4. 验证(闸门 2)

- [x] 4.1 无 key、断网下跑 `uv run pytest`:退出码 0、`failed=0`
- [x] 4.2 确认 `xfailed` 计数与第 3 步隔离清单吻合,无裸 skip/xfail(每个都有 reason)
- [x] 4.3 `openspec validate fix-preexisting-test-debt` 通过
- [x] 4.4 在 tasks 末尾追加"验证结果(一次性运行记录)":passed / xfailed 计数与残留说明

## 5. 验证结果(一次性运行记录)

- **`uv run pytest`(无 key 离线)**:`21 passed, 9 xfailed, 0 failed`,退出码 0(112s)。较改前 `21 failed / 9 passed` 完成转绿。
- **9 个 xfailed**:全部来自 `test_user_behavior_agent.py` 的 phantom 测试(2 个整类 + 1 个方法级),每个带 `_PHANTOM_REASON`,无裸 skip/xfail。
- **新增纳入**:`test_appointment_agent.py::test_should_handle_incomplete_info_gracefully` 为实现期发现的同类签名错位(proposal 未列),已按真实签名补传 `appointment_history` 修复为正常通过,未改 `agents/` 源码(见 3b)。
- **残留**:仅 SQLAlchemy `declarative_base`/`utcnow` 的 Deprecation 警告(预存,与本 change 无关)。
