---
name: setup-environment
description: One-shot environment bootstrapper for the Smart Appointment AI Agent, powered by uv. Creates a uv-managed virtual environment from pyproject.toml / uv.lock, scaffolds a .env file with generic OpenAI-compatible LLM / embedding / OpenWeather keys, prepares the data directory, and verifies the install. Use when user says "setup environment", "一键配置", "初始化环境", "install deps", "配置环境", "setup", "bootstrap", "搭建环境", or whenever a fresh checkout needs to be made runnable.
---

# Setup Environment (uv)

One trigger completes **check uv → create venv → sync deps → scaffold .env → init data dir → verify → (optional) launch app**.

This project is managed with [uv](https://docs.astral.sh/uv/). Dependencies live in `pyproject.toml`, pinned by `uv.lock`. uv creates and manages the `.venv` for you, and will download a compatible Python (3.10–3.12) automatically if one is not installed.

Optional modifiers:
- `--run` after setup, also start `uvicorn` on `127.0.0.1:8001`
- `--force` recreate the `.venv` from scratch
- `--no-verify` skip the import-time verification step

---

## Pipeline

```
Check uv (install hint if missing)
        ↓
Ensure .env (copy from .env.example if missing, then prompt for model keys)
        ↓
uv sync         (creates .venv from pyproject.toml + uv.lock, Python 3.10–3.12)
        ↓
Ensure data/ directory exists
        ↓
Verify imports (fastapi, langchain, faiss, sqlalchemy, mcp …)
        ↓
[optional] uv run uvicorn app:app --host 127.0.0.1 --port 8001
```

> **⚠️ Always use uv / the project-local `.venv` for this repository.**
> Do not run this project with global/system `python`, `pip`, `pytest`, or `uvicorn`; global Python may be 3.13+ and incompatible with LangChain 0.3.x.
> Prefer `uv run <cmd>` — it auto-uses the project `.venv` without manual activation. To activate manually:
> - **Windows (PowerShell)**: `.\.venv\Scripts\Activate.ps1`
> - **Windows (cmd)**:        `.\.venv\Scripts\activate.bat`
> - **macOS / Linux**:        `source .venv/bin/activate`
> - **Direct Windows Python**: `.\.venv\Scripts\python.exe`

---

## Quick Start

### Windows (PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File .github\skills\setup-environment\scripts\setup.ps1
```

### macOS / Linux

```bash
bash .github/skills/setup-environment/scripts/setup.sh
```

The script is idempotent: re-running only patches whatever is missing.

---

## Step-by-Step (when running manually)

### 1. Check uv

Required: **uv** (any recent version). Check with:

```powershell
uv --version
```

If missing, install it:

- **Windows (PowerShell)**: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- **macOS / Linux**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- or `pipx install uv` / `pip install uv`

> uv reads `requires-python = ">=3.10,<3.13"` from `pyproject.toml` and will download a matching CPython automatically.
> Python **3.13 / 3.14 are intentionally excluded**: PEP 649 deferred annotation evaluation in 3.13+ breaks LangChain 0.3.x / pydantic forward-ref evaluation (`TypeError: 'function' object is not subscriptable`).

### 2. Fill model configuration before continuing

Before syncing dependencies or launching the app, ensure `.env` has real model settings. If `.env` is missing, copy `.env.example` to `.env`, then pause and ask the user to fill these fields.

This project uses **two different model capabilities**:

1. **Chat LLM**: used by the appointment, consultation, task-classification, and user-behavior agents to understand user messages and generate replies.
2. **Embedding model**: used by RAG retrieval and technician similarity matching to convert text into vectors.

Do not assume every provider offers both. Chat and embedding settings are intentionally separated in `.env`:

```env
MODEL_PROVIDER=...
LLM_API_KEY=...
LLM_BASE_URL=...
LLM_MODEL=...

EMBEDDING_PROVIDER=...
EMBEDDING_API_KEY=...
EMBEDDING_BASE_URL=...
EMBEDDING_MODEL=...
```

The API key may be the same when one provider supplies both capabilities, such as Qwen, Zhipu, OpenAI, or Azure OpenAI. It may need to be different when the chat provider does not provide embeddings, such as DeepSeek.

Provider choices:

| Provider | Chat LLM | Embedding | Where to get key | Fill in `.env` |
|----------|----------|-----------|------------------|----------------|
| Qwen | Yes | Yes | Alibaba Cloud Bailian / DashScope console | `MODEL_PROVIDER=qwen`, `EMBEDDING_PROVIDER=qwen`; fill `LLM_*` and `EMBEDDING_*`. The API key can usually be the same. |
| DeepSeek | Yes | Usually no general embedding API | DeepSeek Platform | `MODEL_PROVIDER=deepseek`; fill `LLM_*`. Choose another provider for `EMBEDDING_PROVIDER`, usually Qwen, Zhipu, OpenAI, or Azure. |
| Zhipu | Yes | Yes | BigModel console | `MODEL_PROVIDER=zhipu`, `EMBEDDING_PROVIDER=zhipu`; fill `LLM_*` and `EMBEDDING_*`. |
| OpenAI | Yes | Yes | OpenAI Platform | `MODEL_PROVIDER=openai`, `EMBEDDING_PROVIDER=openai`; fill `LLM_*` and `EMBEDDING_*`. |
| Azure OpenAI | Yes | Yes | Azure Portal | Use `MODEL_PROVIDER=azure` and/or `EMBEDDING_PROVIDER=azure`, then add and fill the matching `AZURE_OPENAI_*` values. |

Recommended examples:

```env
# Qwen for both chat and embeddings
MODEL_PROVIDER=qwen
LLM_API_KEY=your_qwen_key
LLM_BASE_URL=your_qwen_openai_compatible_chat_base_url
LLM_MODEL=your_qwen_chat_model

EMBEDDING_PROVIDER=qwen
EMBEDDING_API_KEY=your_qwen_key
EMBEDDING_BASE_URL=your_qwen_openai_compatible_embedding_base_url
EMBEDDING_MODEL=your_qwen_embedding_model
```

```env
# DeepSeek for chat, Qwen for embeddings
MODEL_PROVIDER=deepseek
LLM_API_KEY=your_deepseek_key
LLM_BASE_URL=your_deepseek_openai_compatible_chat_base_url
LLM_MODEL=your_deepseek_chat_model

EMBEDDING_PROVIDER=qwen
EMBEDDING_API_KEY=your_qwen_key
EMBEDDING_BASE_URL=your_qwen_openai_compatible_embedding_base_url
EMBEDDING_MODEL=your_qwen_embedding_model
```

Stop here if any value still looks like `your_..._here`. Tell the user: “Please fill `.env`, then tell me it is ready, and I will continue setup.”

### 3. Sync dependencies (creates the venv)

```powershell
uv sync
```

This single command creates `.venv` (picking a Python 3.10–3.12, downloading one if needed) and installs every dependency from `pyproject.toml`, exactly pinned by `uv.lock`. To include the dev tools (pytest), use `uv sync --dev`. If `--force` was passed, delete `.venv` first so uv rebuilds it from scratch.

`faiss-cpu` may take 1–2 minutes on first install — that is normal.

### 4. Validate `.env`

If a `.env` already exists, leave it alone. Otherwise copy `.env.example` to `.env`. Then check the values:

| Key | Required | Notes |
|-----|----------|-------|
| `MODEL_PROVIDER` | ✅ | `qwen`, `deepseek`, `zhipu`, `openai`, `openai-compatible`, or `azure` |
| `LLM_API_KEY` | ✅ for non-Azure | Chat model API key |
| `LLM_BASE_URL` | ✅ for non-Azure | OpenAI-compatible base URL provided by the selected provider |
| `LLM_MODEL` | ✅ for non-Azure | Chat model name provided by the selected provider |
| `EMBEDDING_PROVIDER` | ✅ | Usually `qwen`, `zhipu`, `openai`, or `azure` |
| `EMBEDDING_API_KEY` | ✅ for non-Azure | Embedding model API key; can match `LLM_API_KEY` |
| `EMBEDDING_BASE_URL` | ✅ for non-Azure | OpenAI-compatible embedding base URL provided by the selected provider |
| `EMBEDDING_MODEL` | ✅ for non-Azure | Embedding model name provided by the selected provider |
| `AZURE_OPENAI_*` | ✅ only for Azure | Used when provider is `azure` |
| `OPENWEATHER_API_KEY` | ⚠ optional | Used by the MCP weather tool |

If any required key still equals the placeholder (`your_..._here`), pause and ask the user to fill it in before continuing. **Never commit a populated `.env`.**

### 5. Ensure data directory

```powershell
New-Item -ItemType Directory -Force -Path data | Out-Null
```

The app writes the SQLite DB and FAISS index cache here on first launch.

### 6. Verify

```powershell
uv run python .github\skills\setup-environment\scripts\verify_env.py
```

This script imports the critical packages and validates the model provider variables.

### 7. (Optional) Launch

```powershell
uv run uvicorn app:app --host 127.0.0.1 --port 8001 --reload
```

Open <http://127.0.0.1:8001/docs> to confirm.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `uv: command not found` / `not recognized` | Install uv (see step 1), then restart the shell so `uv` is on `PATH` |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | Prefer `uv run <cmd>` (no activation needed). Or run: `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` |
| uv cannot find a compatible Python | uv normally downloads one automatically; if blocked, install Python 3.12 (`winget install --id Python.Python.3.12 -e`) and re-run `uv sync` |
| `faiss-cpu` build/download fails | Re-run `uv sync`; ensure 64-bit Python; check network/proxy |
| `mcp` package not found | Confirm the resolved Python is 3.10–3.12; re-run `uv sync` |
| `TypeError: 'function' object is not subscriptable` during LangChain import | A Python 3.13/3.14 interpreter leaked in. `requires-python` excludes it; run via `uv run`/`.venv`, not system Python |
| `ModuleNotFoundError` after install | The shell is using system Python. Use `uv run <cmd>` or re-activate `.venv` |
| `uv.lock` out of sync with `pyproject.toml` | Run `uv lock` then `uv sync` |
| Port 8001 already in use | Stop the previous server or pass `--port 8002` to uvicorn |
| Model auth errors at startup | Re-check `MODEL_PROVIDER`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, and embedding settings in `.env` |

---

## Files in this skill

```
.github/skills/setup-environment/
├── SKILL.md           ← this file
└── scripts/
    ├── setup.ps1      ← one-shot uv bootstrapper for Windows
    ├── setup.sh       ← one-shot uv bootstrapper for macOS/Linux
    └── verify_env.py  ← import-level smoke test
```

Dependencies are declared in `pyproject.toml` and pinned in `uv.lock` at the project root. A `.env.example` template also lives at the project root (sibling of `pyproject.toml`) so the bootstrap scripts can copy it on a clean checkout.
