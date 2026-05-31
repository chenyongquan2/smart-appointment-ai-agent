<#
.SYNOPSIS
  One-shot environment bootstrapper for the Smart Appointment AI Agent (Windows, uv).

.DESCRIPTION
  - Validates that uv is installed (prints install hint otherwise)
  - Scaffolds .env from .env.example and gates on model configuration
  - Runs `uv sync` to create .venv from pyproject.toml + uv.lock (Python 3.10-3.12)
  - Ensures data/ directory exists
  - Runs verify_env.py via `uv run`
  - Optionally launches uvicorn

.PARAMETER Force
  Recreate the .venv from scratch before syncing.

.PARAMETER Run
  After setup, launch `uvicorn app:app` on 127.0.0.1:8001.

.PARAMETER NoVerify
  Skip the verify_env.py import smoke test.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .github\skills\setup-environment\scripts\setup.ps1
  powershell -ExecutionPolicy Bypass -File .github\skills\setup-environment\scripts\setup.ps1 -Force -Run
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Run,
    [switch]$NoVerify
)

$ErrorActionPreference = 'Stop'

# Resolve project root: scripts/ -> setup-environment/ -> skills/ -> .github/ -> ROOT
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir '..\..\..\..')
Set-Location $ProjectRoot

function Write-Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok  ([string]$msg) { Write-Host "[OK] $msg"   -ForegroundColor Green }
function Write-Warn2([string]$msg){ Write-Host "[!]  $msg"   -ForegroundColor Yellow }
function Write-Err ([string]$msg) { Write-Host "[X]  $msg"   -ForegroundColor Red }

function Show-ModelConfigHelp {
  Write-Host "`nModel configuration is required before setup can continue." -ForegroundColor Yellow
  Write-Host "You can use one of these providers:" -ForegroundColor Yellow
  Write-Host "  - Qwen:     get a key from Alibaba Cloud Bailian / DashScope (https://bailian.console.aliyun.com/), fill MODEL_PROVIDER=qwen, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL."
  Write-Host "  - DeepSeek: get a key from DeepSeek Platform (https://platform.deepseek.com/api_keys), fill MODEL_PROVIDER=deepseek, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL. Use Qwen/Zhipu/OpenAI for embeddings."
  Write-Host "  - Zhipu:    get a key from BigModel (https://bigmodel.cn/usercenter/proj-mgmt/apikeys), fill MODEL_PROVIDER=zhipu, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL."
  Write-Host "  - OpenAI:   get a key from OpenAI Platform (https://platform.openai.com/api-keys), fill MODEL_PROVIDER=openai, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL."
  Write-Host "  - Azure:    get a key from Azure Portal (https://portal.azure.com/), fill MODEL_PROVIDER=azure and the AZURE_OPENAI_* values."
  Write-Host "`nFill these values in .env, then tell me you are ready and I will continue setup." -ForegroundColor Yellow
}

function Get-EnvValues([string]$content) {
  $values = @{}
  foreach ($rawLine in $content -split "`n") {
    $line = $rawLine.Trim()
    if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) { continue }
    $key, $value = $line.Split('=', 2)
    $values[$key.Trim()] = $value.Trim().Trim('"').Trim("'")
  }
  return $values
}

function Get-IncompleteModelKeys([string]$content) {
  $values = Get-EnvValues $content
  $provider = 'azure'
  if ($values.ContainsKey('MODEL_PROVIDER') -and $values['MODEL_PROVIDER']) {
    $provider = $values['MODEL_PROVIDER']
  }
  $provider = $provider.ToLowerInvariant()

  $embeddingProvider = $provider
  if ($values.ContainsKey('EMBEDDING_PROVIDER') -and $values['EMBEDDING_PROVIDER']) {
    $embeddingProvider = $values['EMBEDDING_PROVIDER']
  }
  $embeddingProvider = $embeddingProvider.ToLowerInvariant()
  $required = @('MODEL_PROVIDER')

  if ($provider -eq 'azure') {
    $required += @('AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_ENDPOINT', 'AZURE_OPENAI_DEPLOYMENT', 'AZURE_OPENAI_VERSION')
  } else {
    $required += @('LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL')
  }

  $required += 'EMBEDDING_PROVIDER'
  if ($embeddingProvider -eq 'azure') {
    $required += @('AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_ENDPOINT_EMBEDDING', 'AZURE_OPENAI_DEPLOYMENT_EMBEDDING')
  } else {
    $required += @('EMBEDDING_API_KEY', 'EMBEDDING_BASE_URL', 'EMBEDDING_MODEL')
  }

  $incomplete = @()
  foreach ($key in $required) {
    if (-not $values.ContainsKey($key) -or -not $values[$key] -or $values[$key] -match 'your_[a-zA-Z0-9_]*_here') {
      $incomplete += $key
    }
  }
  return $incomplete | Select-Object -Unique
}

# ---------------------------------------------------------------- 1. uv
# Dependencies are managed by uv via pyproject.toml + uv.lock. uv reads
# requires-python = ">=3.10,<3.13" and downloads a compatible CPython if needed.
# Python 3.13/3.14 are excluded: PEP 649 deferred annotation evaluation breaks
# LangChain 0.3.x (TypeError: 'function' object is not subscriptable).
Write-Step "Checking uv"

$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCmd) {
    Write-Err "uv is not installed."
    Write-Host "Install it with one of:" -ForegroundColor Yellow
    Write-Host '  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
    Write-Host '  pip install uv'
    Write-Host "Then restart the shell and re-run this script." -ForegroundColor Yellow
    exit 1
}
$uvVersion = (& uv --version) 2>$null
Write-Ok "uv found: $uvVersion"

# ---------------------------------------------------------------- 2. .env gate
Write-Step "Checking model configuration"
$EnvFile     = Join-Path $ProjectRoot '.env'
$EnvExample  = Join-Path $ProjectRoot '.env.example'

if (-not (Test-Path $EnvExample)) {
  @"
MODEL_PROVIDER=qwen
LLM_API_KEY=your_llm_api_key_here
LLM_BASE_URL=your_openai_compatible_chat_base_url_here
LLM_MODEL=your_chat_model_name_here
EMBEDDING_PROVIDER=qwen
EMBEDDING_API_KEY=your_embedding_api_key_here
EMBEDDING_BASE_URL=your_openai_compatible_embedding_base_url_here
EMBEDDING_MODEL=your_embedding_model_name_here
OPENWEATHER_API_KEY=your_openweather_api_key_here
"@ | Set-Content -Path $EnvExample -Encoding UTF8
  Write-Ok ".env.example created"
}

if (-not (Test-Path $EnvFile)) {
  Copy-Item $EnvExample $EnvFile
  Write-Warn2 ".env was missing. A template was copied from .env.example."
}

$envContent = Get-Content $EnvFile -Raw
$incompleteKeys = @(Get-IncompleteModelKeys $envContent)
if ($incompleteKeys.Count -gt 0) {
  Show-ModelConfigHelp
  Write-Host "`nMissing or placeholder values: $($incompleteKeys -join ', ')" -ForegroundColor Yellow
  exit 2
}
Write-Ok ".env model configuration looks filled"

# ---------------------------------------------------------------- 3. uv sync
Write-Step "Syncing dependencies with uv (this may take a minute)"
if ($Force -and (Test-Path .venv)) {
    Write-Warn2 "Removing existing .venv (forced)"
    Remove-Item -Recurse -Force .venv
}

& uv sync
if ($LASTEXITCODE -ne 0) { Write-Err "uv sync failed"; exit 1 }
Write-Ok "Dependencies synced into .venv"

# ---------------------------------------------------------------- 4. data dir
Write-Step "Ensuring data/ directory"
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot 'data') | Out-Null
Write-Ok "data/ ready"

# ---------------------------------------------------------------- 5. verify
if (-not $NoVerify) {
    Write-Step "Verifying installation"
    & uv run python (Join-Path $ScriptDir 'verify_env.py')
    if ($LASTEXITCODE -ne 0) { Write-Err "verify_env.py failed"; exit 1 }
}

Write-Host "`n========================================================" -ForegroundColor Green
Write-Host " Setup complete." -ForegroundColor Green
Write-Host " Run app (no activation needed):  uv run uvicorn app:app --host 127.0.0.1 --port 8001 --reload" -ForegroundColor Green
Write-Host " Or activate the venv with:       .\.venv\Scripts\Activate.ps1" -ForegroundColor Green
Write-Host "========================================================`n" -ForegroundColor Green

# ---------------------------------------------------------------- 6. optional run
if ($Run) {
    Write-Step "Launching uvicorn on 127.0.0.1:8001"
    & uv run uvicorn app:app --host 127.0.0.1 --port 8001 --reload
}
