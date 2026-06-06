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

会自动创建 `.venv`（Python 3.10–3.12）并按 `uv.lock` 安装全部依赖。首次安装 `faiss-cpu` 可能要 1–2 分钟，属正常。

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

> 提示：始终用 `uv run <命令>` 运行项目，它会自动使用项目内的 `.venv`，无需手动激活。
