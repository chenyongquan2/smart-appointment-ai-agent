#!/usr/bin/env bash
# One-shot environment bootstrapper for the Smart Appointment AI Agent (macOS / Linux, uv).
#
# Dependencies are managed by uv via pyproject.toml + uv.lock.
#
# Flags:
#   --force        recreate .venv from scratch before syncing
#   --run          after setup, launch uvicorn on 127.0.0.1:8001
#   --no-verify    skip verify_env.py
set -euo pipefail

FORCE=0
RUN=0
VERIFY=1
for arg in "$@"; do
    case "$arg" in
        --force)     FORCE=1 ;;
        --run)       RUN=1 ;;
        --no-verify) VERIFY=0 ;;
        *) echo "Unknown flag: $arg" >&2; exit 2 ;;
    esac
done

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$( cd -- "$SCRIPT_DIR/../../../.." &> /dev/null && pwd )"
cd "$PROJECT_ROOT"

C_CYAN='\033[36m'; C_GREEN='\033[32m'; C_YELLOW='\033[33m'; C_RED='\033[31m'; C_OFF='\033[0m'
step() { printf "\n${C_CYAN}==> %s${C_OFF}\n" "$1"; }
ok()   { printf "${C_GREEN}[OK] %s${C_OFF}\n" "$1"; }
warn() { printf "${C_YELLOW}[!]  %s${C_OFF}\n" "$1"; }
err()  { printf "${C_RED}[X]  %s${C_OFF}\n" "$1" >&2; }

show_model_config_help() {
    printf "\n${C_YELLOW}Model configuration is required before setup can continue.${C_OFF}\n"
    printf "${C_YELLOW}You can use one of these providers:${C_OFF}\n"
    printf "  - Qwen:     get a key from Alibaba Cloud Bailian / DashScope (https://bailian.console.aliyun.com/), fill MODEL_PROVIDER=qwen, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL.\n"
    printf "  - DeepSeek: get a key from DeepSeek Platform (https://platform.deepseek.com/api_keys), fill MODEL_PROVIDER=deepseek, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL. Use Qwen/Zhipu/OpenAI for embeddings.\n"
    printf "  - Zhipu:    get a key from BigModel (https://bigmodel.cn/usercenter/proj-mgmt/apikeys), fill MODEL_PROVIDER=zhipu, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL.\n"
    printf "  - OpenAI:   get a key from OpenAI Platform (https://platform.openai.com/api-keys), fill MODEL_PROVIDER=openai, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL.\n"
    printf "  - Azure:    get a key from Azure Portal (https://portal.azure.com/), fill MODEL_PROVIDER=azure and the AZURE_OPENAI_* values.\n"
    printf "\n${C_YELLOW}Fill these values in .env, then tell me you are ready and I will continue setup.${C_OFF}\n"
}

get_env_value() {
    local key="$1"
    if [ ! -f "$ENV_FILE" ]; then
        return 0
    fi
    grep -E "^${key}=" "$ENV_FILE" | tail -n 1 | cut -d '=' -f 2- | sed "s/^['\"]//;s/['\"]$//"
}

is_incomplete_value() {
    local value="$1"
    [ -z "$value" ] || printf '%s' "$value" | grep -q 'your_[A-Za-z0-9_]*_here'
}

collect_incomplete_model_keys() {
    local provider embedding_provider required key value incomplete
    provider="$(get_env_value MODEL_PROVIDER)"
    [ -n "$provider" ] || provider="azure"
    provider="$(printf '%s' "$provider" | tr '[:upper:]' '[:lower:]')"
    embedding_provider="$(get_env_value EMBEDDING_PROVIDER)"
    [ -n "$embedding_provider" ] || embedding_provider="$provider"
    embedding_provider="$(printf '%s' "$embedding_provider" | tr '[:upper:]' '[:lower:]')"

    required="MODEL_PROVIDER"
    if [ "$provider" = "azure" ]; then
        required="$required AZURE_OPENAI_API_KEY AZURE_OPENAI_ENDPOINT AZURE_OPENAI_DEPLOYMENT AZURE_OPENAI_VERSION"
    else
        required="$required LLM_API_KEY LLM_BASE_URL LLM_MODEL"
    fi

    required="$required EMBEDDING_PROVIDER"
    if [ "$embedding_provider" = "azure" ]; then
        required="$required AZURE_OPENAI_API_KEY AZURE_OPENAI_ENDPOINT_EMBEDDING AZURE_OPENAI_DEPLOYMENT_EMBEDDING"
    else
        required="$required EMBEDDING_API_KEY EMBEDDING_BASE_URL EMBEDDING_MODEL"
    fi

    incomplete=""
    for key in $required; do
        value="$(get_env_value "$key")"
        if is_incomplete_value "$value"; then
            incomplete="$incomplete $key"
        fi
    done
    printf '%s' "$incomplete" | xargs
}

# ----------------------------------------------------------- 1. uv
# uv reads requires-python = ">=3.10,<3.13" from pyproject.toml and downloads a
# compatible CPython if needed. Python 3.13/3.14 are excluded: PEP 649 deferred
# annotation evaluation breaks LangChain 0.3.x.
step "Checking uv"
if ! command -v uv >/dev/null 2>&1; then
    err "uv is not installed."
    printf "${C_YELLOW}Install it with one of:${C_OFF}\n"
    printf "  curl -LsSf https://astral.sh/uv/install.sh | sh\n"
    printf "  pip install uv\n"
    printf "${C_YELLOW}Then restart the shell and re-run this script.${C_OFF}\n"
    exit 1
fi
ok "uv found: $(uv --version)"

# ----------------------------------------------------------- 2. .env gate
step "Checking model configuration"
ENV_FILE="$PROJECT_ROOT/.env"
ENV_EXAMPLE="$PROJECT_ROOT/.env.example"
if [ ! -f "$ENV_EXAMPLE" ]; then
    cat > "$ENV_EXAMPLE" <<'EOF'
MODEL_PROVIDER=qwen
LLM_API_KEY=your_llm_api_key_here
LLM_BASE_URL=your_openai_compatible_chat_base_url_here
LLM_MODEL=your_chat_model_name_here
EMBEDDING_PROVIDER=qwen
EMBEDDING_API_KEY=your_embedding_api_key_here
EMBEDDING_BASE_URL=your_openai_compatible_embedding_base_url_here
EMBEDDING_MODEL=your_embedding_model_name_here
OPENWEATHER_API_KEY=your_openweather_api_key_here
EOF
    ok ".env.example created"
fi
if [ ! -f "$ENV_FILE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    warn ".env was missing. A template was copied from .env.example."
fi
INCOMPLETE_KEYS="$(collect_incomplete_model_keys)"
if [ -n "$INCOMPLETE_KEYS" ]; then
    show_model_config_help
    warn "Missing or placeholder values: $INCOMPLETE_KEYS"
    exit 2
fi
ok ".env model configuration looks filled"

# ----------------------------------------------------------- 3. uv sync
step "Syncing dependencies with uv (this may take a minute)"
if [ "$FORCE" -eq 1 ] && [ -d .venv ]; then
    warn "Removing existing .venv (forced)"; rm -rf .venv
fi
uv sync
ok "Dependencies synced into .venv"

# ----------------------------------------------------------- 4. data dir
step "Ensuring data/ directory"
mkdir -p "$PROJECT_ROOT/data"
ok "data/ ready"

# ----------------------------------------------------------- 5. verify
if [ "$VERIFY" -eq 1 ]; then
    step "Verifying installation"
    uv run python "$SCRIPT_DIR/verify_env.py"
fi

cat <<EOF

${C_GREEN}========================================================
 Setup complete.
 Run app (no activation needed):  uv run uvicorn app:app --host 127.0.0.1 --port 8001 --reload
 Or activate the venv with:       source .venv/bin/activate
========================================================${C_OFF}

EOF

# ----------------------------------------------------------- 6. optional run
if [ "$RUN" -eq 1 ]; then
    step "Launching uvicorn on 127.0.0.1:8001"
    exec uv run uvicorn app:app --host 127.0.0.1 --port 8001 --reload
fi
