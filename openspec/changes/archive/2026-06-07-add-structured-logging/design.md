## Context

Phase 0 路线要求"最简 trace:结构化 logging(JSON)替换 print"。现状:`app.py` 用 `logging.basicConfig(level=INFO)`(纯文本);`agents/` 散布 ~20 处 `print`(启动语、`[DEBUG]` 转交、状态转换、RAG 检索打印、`except` 里的失败打印),`api/knowledge.py` 还有 1 处;`agents/user_behavior/*` 已是 `getLogger(__name__)` 的正确写法,可作样板。

约束:`agents/` 即将被重构为 `harness/`,因此本次**只动输出方式**,不碰业务;全链路 tracer/每步 input-output 记录属 Phase 6,本次不做(已与发起人确认取"机械替换"深度)。

## Goals / Non-Goals

**Goals:**
- 一个最小的中央 JSON 日志配置,`app.py` 启动调用。
- `agents/` + `api/knowledge.py` 的 `print` 全部换成语义正确的 `logger` 调用。
- 零行为回归,`uv run pytest` 保持全绿。

**Non-Goals:**
- 不建 Phase 6 的 tracer / 每步 input-output trace 助手。
- 不改业务逻辑、控制流、函数签名;不动 `services/`/`db/`/`config/model_provider.py`。
- 不引入第三方日志库(如 structlog)——标准库够用。

## Decisions

### D1:用标准库 `logging` + 自写最小 `JsonFormatter`,不引第三方
新增 `config/logging_setup.py`:一个继承 `logging.Formatter` 的 `JsonFormatter`(`format()` 里 `json.dumps` 出 `timestamp/level/logger/message`,有异常则带 `exc_info` 文本),外加 `setup_logging(level=INFO)` 配 root handler 到 stdout。
- **为何标准库**:零新依赖、够用、与现有 `getLogger` 写法无缝;structlog 收益不抵成本。
- **为何放 `config/`**:与现有 `config/model_provider.py` 等基础设施同层;`config/` 是保留资产,新增模块不违背"不重写 config"(那指不重写已有的 provider 抽象)。

### D2:`app.py` 用 `setup_logging()` 取代 `basicConfig`
启动处一行替换。
- **风险**:Windows 控制台编码——已有 `3bc6c41` 强制 UTF-8,JSON(含中文)按 `ensure_ascii=False` 输出需确保 handler 用 UTF-8;`setup_logging` 里显式设 stream 编码或 `ensure_ascii=True` 兜底。决定:`ensure_ascii=False` + 复用现有 UTF-8 stdout 设置,保留中文可读。

### D3:逐文件机械替换,级别映射固定
- 启动语("已启动")、状态转换、`[DEBUG]` 转交、RAG 检索明细 → `logger.debug`/`logger.info`(转交类原是 `[DEBUG]` 前缀 → `debug`;启动/路由 → `info`)。
- `except` 块里的失败打印 → `logger.error(msg, exc_info=True)`。
- 每文件顶部 `logger = logging.getLogger(__name__)`(模块级)或沿用类内 `self.logger`,与 `user_behavior` 现有写法一致。
- **为何固定映射**:避免主观发挥导致控制流/语义漂移;评审可逐条核对。

## Risks / Trade-offs

- **改动文件多(~11 个)但每处极小** → 逐文件小步替换,最后统一 grep 校验无残留 + 跑全量测试。
- **RAG 检索那几处 print 含 emoji/多行** → 合并为单条结构化 `debug`,信息不丢、不再裸打。
- **日志级别默认 INFO 会吞掉 debug** → 可接受;需要详细 trace 时调 `setup_logging(level=DEBUG)`,这正是结构化的好处(原 print 无法关）。
- **测试捕获日志** → 现有测试不断言 stdout 文本(classification 断言的是返回值),替换 print 不影响;仍以全量 pytest 兜底。

## Migration Plan

1. 加 `config/logging_setup.py`(JsonFormatter + setup_logging)。
2. `app.py` 改用 `setup_logging()`。
3. 逐文件替换 `agents/` 与 `api/knowledge.py` 的 print。
4. grep 校验无残留 print;`uv run pytest` 全绿;手动启动看一条 JSON 日志。
- **回滚**:纯输出层改动,`git revert` 即可。

## Open Questions

- 无。深度(机械替换)与范围(agents/+api/)已与发起人确认。
