# 运行指南

本项目使用 [uv](https://docs.astral.sh/uv/) 管理依赖和虚拟环境。下面是最精简的运行步骤，完整说明见 [README.md](README.md)。

## 前置要求

- 已安装 uv（`uv --version` 能输出版本即可）
  - Windows 安装：`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
  - macOS / Linux：`curl -LsSf https://astral.sh/uv/install.sh | sh`

## 三步跑起来

### 1. 安装依赖

```bash
uv sync
```

会自动创建 `.venv`（Python 3.10–3.12）并按 `uv.lock` 安装全部依赖。首次安装 `faiss-cpu` 可能要 1–2 分钟，属正常（它现在只用于技师专长相似度匹配）。

### 2. 配置 `.env`

```bash
cp .env.example .env      # Windows PowerShell: Copy-Item .env.example .env
```

在 `.env` 中填入大模型与 Embedding 的配置（两者分开，可能用不同 Provider）：

```env
MODEL_PROVIDER=qwen
LLM_API_KEY=...
LLM_BASE_URL=...
LLM_MODEL=...

EMBEDDING_PROVIDER=qwen
EMBEDDING_API_KEY=...
EMBEDDING_BASE_URL=...
EMBEDDING_MODEL=...
```

> ℹ Embedding 现在只服务**技师专长相似度匹配**。知识库检索已不在本仓——本地 RAG
> （SQLite+FAISS）已移除，`search_knowledge` 走 [services/knowledge_search.py](services/knowledge_search.py)
> 的可替换端口，未注入实现时会明确报「知识库尚未接入」，待接入独立 RAG 项目。

`OPENWEATHER_API_KEY` 是可选的（MCP 天气工具用），不填不影响主流程。

可选：验证环境是否就绪

```bash
uv run python .claude/setup-environment/scripts/verify_env.py
```

### 3. 启动服务

```bash
uv run uvicorn app:app --host 127.0.0.1 --port 8001 --reload
```

启动后访问：

- Web 页面：http://127.0.0.1:8001
- API 文档（Swagger）：http://127.0.0.1:8001/docs
- ReDoc 文档：http://127.0.0.1:8001/redoc

`--reload` 会在改代码后自动重启，适合开发学习。停止服务按 `Ctrl+C`。

## 接入飞书（可选）

把同一个 Agent 暴露到飞书群里 @ 对话。申请应用与配置权限的完整步骤见
[docs/feishu-app-setup.md](docs/feishu-app-setup.md)，这里只讲跑起来。

### 配置

在 `.env` 里补上（键名说明见 `.env.example`）：

```env
FEISHU_ENABLED=true
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FEISHU_DOMAIN=https://open.feishu.cn
FEISHU_SESSION_SCOPE=reply
```

`FEISHU_ENABLED` 默认 `false`——没填凭据时不该去连。`FEISHU_DOMAIN` 换成
`https://open.larksuite.com` 即接国际版 Lark（同一份代码，两个实例）。

### 启动（⚠ 必须单 worker）

```bash
uv run uvicorn app:app --host 127.0.0.1 --port 8001 --workers 1
```

**`--workers 1` 是硬约束，不是建议。** 多 worker 会起多份长连接，同一条消息被不同进程
各消费一次；而事件去重表是**进程内**的，拦不住跨进程重复——重复消费意味着重复下单
（`create_appointment` 目前没有幂等键）。uvicorn 默认就是单 worker，别去加。

开发时若要用 `--reload`，建议先把 `FEISHU_ENABLED` 改成 `false`：每次热重启都会断开重连，
噪音大且可能重复消费。

启动成功的日志长这样：

```
飞书机器人自检通过：oncall-bot open_id=ou_... 已启用
connected to wss://msg-frontier.feishu.cn/ws/v2 ...
飞书接入已启动
```

自检失败会打出一条明确的排查清单（机器人能力 / 权限 / 版本是否发布 / 凭据），且
**不会让 Web 服务起不来**——飞书接入是可选能力，它连不上不影响其它功能。

### 怎么用

在群里 @ 机器人提问。机器人会：

1. 先回一条「收到，正在处理…」（长任务不至于让人干瞪眼）
2. 处理完把结果**发进同一个话题**，主聊天流只留一条折叠入口

**想继续多轮对话，就在那个话题里接着说**（而不是重新 @ 一次）。会话键取自回复链
（`root_id`），所以话题内的往来都落在同一个会话；重新 @ 一次则是开一段新对话，
上下文互不可见。这个语义可用 `FEISHU_SESSION_SCOPE=chat` 改成"整群共用一条会话"，
但那样同群所有人会共享一份历史、且同群消息串行执行。

### 可调参数

| 变量 | 默认 | 说明 |
|---|---|---|
| `EXECUTOR_MAX_CONCURRENCY` | 10 | 跨会话并行上限 |
| `EXECUTOR_MAX_QUEUE_PER_SESSION` | 5 | 单会话排队深度；超出即回「稍后再发」，防连发刷屏 |
| `EXECUTOR_WALL_CLOCK_TIMEOUT` | 600 | 单任务墙钟上限（秒），超时投一条带副作用提示的兜底回复 |
| `EXECUTOR_ENABLED` | true | 设 `false` 让 Web 走改造前的直调路径（应急回退） |

## 运行测试

```bash
uv run pytest                                          # 全部测试
uv run pytest tests/test_task_classification_agent.py  # 单个文件
```

## 常见问题

| 现象 | 原因 / 解决 |
|------|------------|
| `WinError 10013` 套接字访问被拒 | 端口已被占用。换端口：`--port 8002`，或先停掉占用 8001 的进程 |
| `uv: command not found` | uv 未安装或不在 PATH，安装后重开终端 |
| `TypeError: 'function' object is not subscriptable` | 用了 Python 3.13+。本项目需 3.10–3.12，务必用 `uv run` 而非系统 Python |
| `ModuleNotFoundError` | 用了系统 Python。改用 `uv run <命令>` |
| 聊天报模型鉴权错误 | 检查 `.env` 里的 `LLM_*` / `EMBEDDING_*` 配置 |
| 咨询类问题答「知识库尚未接入」 | 预期行为：本地 RAG 已移除，独立 RAG 项目尚未接入（注入端口实现后即恢复） |
| 飞书连上了但收不到消息 | ① 消息没真的 @ 到机器人；② 事件订阅里没加 `im.message.receive_v1`；③ 权限改动后没重新发布版本 |
| 同一条飞书消息被回复两次 | 用了多 worker。必须 `--workers 1`（去重表是进程内的） |
| 飞书里多轮对话接不上 | 在话题里接着说，而不是重新 @ 一次（后者是开新会话，见上文「怎么用」） |
| 启动报「取不到机器人信息」 | 按日志里的清单逐项核对：机器人能力是否启用、权限是否勾选、版本是否发布通过、凭据是否正确 |

> 提示：始终用 `uv run <命令>` 运行项目，它会自动使用项目内的 `.venv`，无需手动激活。
