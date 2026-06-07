## Why

Phase 0 的第三项"引入最简 trace:用结构化 logging(JSON)替换 `print`"尚未落地。当前 `agents/` 层散布 ~20 处 `print`(含 `task_classification_agent.py:83` 的 `[DEBUG]`、错误吞进 stdout、状态转换打印等),`api/knowledge.py` 还有 1 处。这些输出无级别、无结构、无法过滤或采集,重构 `agents/` → `harness/` 时既看不清每步发生了什么,也无法接入后续 Phase 6 的可观测性。先把"打印"换成"结构化日志",是最便宜的 trace 起点。

## What Changes

- **建中央 JSON logging 配置**:新增一个最小的日志初始化模块(JSON formatter + `setup_logging()`),输出含 `timestamp / level / logger / message` 等字段的单行 JSON;由 `app.py` 在启动时调用,替换现有 `logging.basicConfig(level=INFO)` 的纯文本配置。
- **机械替换 `print` → `logger`**:把 `agents/`(~20 处)与 `api/knowledge.py`(1 处)的 `print` 按语义换成 `logger.{debug,info,error}`:
  - 启动/状态/路由类(如"咨询机器人已启动"、状态转换、`[DEBUG]` 转交) → `debug`/`info`
  - `except` 块里的失败打印 → `logger.error(..., exc_info=True)`
  - 每个模块用 `logging.getLogger(__name__)`,沿用已有 `user_behavior` 的写法。
- **范围红线**:**仅做"打印→结构化日志"的机械替换 + 一个日志配置模块**。不改业务逻辑、不改控制流、不动 `services/`/`db/`,**不**引入 Phase 6 的全链路 tracer / 每步 input-output trace 助手(那是后续阶段)。

## Capabilities

### New Capabilities
- `structured-logging`: 全应用统一的结构化(JSON)日志:有级别、可过滤、可被采集;`agents/`/`api/` 不再用 `print` 向 stdout 裸打。

### Modified Capabilities
<!-- 无 spec 级行为变更 -->

## Impact

- **新增**:一个日志配置模块(暂定 `config/logging_setup.py`,提供 JSON formatter 与 `setup_logging()`)。
- **修改**:`app.py`(调用 `setup_logging()` 取代 `basicConfig`);`agents/` 下含 `print` 的 ~10 个文件;`api/knowledge.py`。
- **不影响**:业务逻辑、控制流、`services/`/`db/`/`config/model_provider.py`、`evals/`、测试断言。
- **验收**:`agents/` 与 `api/knowledge.py` 无残留 `print`;启动后日志为结构化 JSON;`uv run pytest` 仍全绿(无回归)。
