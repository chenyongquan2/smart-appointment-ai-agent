## 1. 中央 JSON 日志配置

- [x] 1.1 新增 `config/logging_setup.py`:`JsonFormatter`(输出含 `timestamp/level/logger/message`,异常带 `exc_info`,`ensure_ascii=False`)+ `setup_logging(level=INFO)` 配 root handler 到 stdout(并尽力把 Windows stdout 重配为 UTF-8)
- [x] 1.2 `app.py` 用 `setup_logging()` 取代现有 `logging.basicConfig(level=logging.INFO)`
- [x] 1.3 冒烟:调一次 logger,确认输出为可解析的单行 JSON、中文 + exc_info 正常

## 2. 替换 agents/ 的 print

- [x] 2.1 `agents/task_classification_agent.py`(2 处 `[DEBUG]` 转交 → `logger.debug`)
- [x] 2.2 `agents/task_classification/`:`task_classifier.py`(error)、`state_manager.py`(状态转换→debug、强制重置→info)、`unrelated_handler.py`(info×2)
- [x] 2.3 `agents/consultant_agent.py`(启动语→info)与 `agents/consultant/`:`consultation_classifier.py`(error)、`knowledge_retriever.py`(初始化→info、检索明细合并为单条→debug)、`consultation_processor.py`(error)
- [x] 2.4 `agents/appointment/`:`appointment_database.py`(2 处 error)、`appointment_processor.py`(error)、`message_builder.py`(2 处 error)
- [x] 2.5 每个改动文件确保有 `logger = logging.getLogger(__name__)`

## 3. 替换 api/ 的 print

- [x] 3.1 `api/knowledge.py:36`(获取 categories 失败 → `logger.error(..., exc_info=True)`)

## 4. 验证(闸门 2)

- [x] 4.1 grep 校验:`agents/`(排除测试/`__pycache__`)与 `api/knowledge.py` 无残留 `print(`
- [x] 4.2 `uv run pytest` 全绿(`failed=0`,xfailed 计数与上一个 change 一致)
- [x] 4.3 冒烟确认日志为结构化 JSON(见 1.3)
- [x] 4.4 `openspec validate add-structured-logging` 通过
- [x] 4.5 末尾追加"验证结果(一次性运行记录)":替换处数、测试结果、残留说明

## 5. 验证结果(一次性运行记录)

- **替换处数**:`agents/` 20 处 + `api/knowledge.py` 1 处 = 共 21 处 `print` → `logger`;新增 `config/logging_setup.py`(JsonFormatter + setup_logging);`app.py` 由 `basicConfig` 改为 `setup_logging()`。
- **残留校验**:`agents/`(排除测试/`__pycache__`)与 `api/knowledge.py` 已无 `print(`。
- **级别映射**:启动/路由/重置 → `info`;`[DEBUG]` 转交、状态转换、RAG 检索明细 → `debug`;所有 `except` 块 → `logger.error(..., exc_info=True)`。
- **JSON 冒烟**:`setup_logging()` 后日志为可解析单行 JSON,中文 + `exc_info` 正常(Windows UTF-8 兜底生效)。
- **回归**:`uv run pytest` = `21 passed, 9 xfailed, 0 failed`(与上一个 change 一致,无回归)。
