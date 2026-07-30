"""Model provider factory for chat LLMs and embeddings.

Supports Azure OpenAI and OpenAI-compatible providers such as Qwen,
DeepSeek, Zhipu, and OpenAI by switching environment variables.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_openai import (
    AzureChatOpenAI,
    AzureOpenAIEmbeddings,
    ChatOpenAI,
    OpenAIEmbeddings,
)
from pydantic import SecretStr

load_dotenv()


CHAT_PROVIDERS = {"openai", "qwen", "deepseek", "zhipu", "openai-compatible"}
EMBEDDING_PROVIDERS = {"openai", "qwen", "zhipu", "openai-compatible"}

# 嵌入请求的默认超时（秒）。
# 为什么必须显式设置：不传的话落到 openai 客户端默认的 **600 秒**——对一次「无生成的
# 单次短请求」而言等于没有上限，实测已导致跑批挂死十余分钟。向量化正常在秒级完成，
# 20 秒留足网络抖动余量，同时远小于任务墙钟（600s）与 LLM 单次超时（30s）的量级秩序。
# 见 change fix-embedding-timeout-blocking 的 design D1。
DEFAULT_EMBEDDING_TIMEOUT = 20.0


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def get_model_provider() -> str:
    """Return configured provider, defaulting to Azure for backward compatibility."""
    return (_env("MODEL_PROVIDER", "azure") or "azure").strip().lower()


def create_chat_model(temperature: float = 0):
    """Create a chat model from environment configuration.

    Azure-compatible env vars:
        MODEL_PROVIDER=azure
        AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT,
        AZURE_OPENAI_VERSION

    OpenAI-compatible env vars:
        MODEL_PROVIDER=qwen|deepseek|zhipu|openai|openai-compatible
        LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
    """
    provider = get_model_provider()

    if provider == "azure":
        return AzureChatOpenAI(
            azure_deployment=_env("AZURE_OPENAI_DEPLOYMENT"),
            api_version=_env("AZURE_OPENAI_VERSION"),
            temperature=temperature,
            azure_endpoint=_env("AZURE_OPENAI_ENDPOINT"),
            api_key=SecretStr(_env("AZURE_OPENAI_API_KEY", "") or ""),
        )

    if provider in CHAT_PROVIDERS:
        return ChatOpenAI(
            model=_env("LLM_MODEL", "qwen-plus") or "qwen-plus",
            api_key=SecretStr(_env("LLM_API_KEY", "") or ""),
            base_url=_env("LLM_BASE_URL"),
            temperature=temperature,
        )

    raise ValueError(
        f"Unsupported MODEL_PROVIDER={provider!r}. "
        "Use azure, qwen, deepseek, zhipu, openai, or openai-compatible."
    )


def resolve_embedding_timeout(timeout: float | None = None) -> float:
    """Resolve the embedding request timeout in seconds.

    Precedence: explicit argument > ``EMBEDDING_TIMEOUT_SECONDS`` env >
    ``DEFAULT_EMBEDDING_TIMEOUT``. A malformed env value falls back to the default
    rather than raising — a typo in configuration must not take the service down.
    """
    if timeout is not None:
        return float(timeout)
    raw = _env("EMBEDDING_TIMEOUT_SECONDS")
    if raw is None:
        return DEFAULT_EMBEDDING_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_EMBEDDING_TIMEOUT


def create_embedding_model(timeout: float | None = None):
    """Create an embedding model from environment configuration.

    Args:
        timeout: Request timeout in seconds. Defaults to
            ``EMBEDDING_TIMEOUT_SECONDS`` or ``DEFAULT_EMBEDDING_TIMEOUT``.

    The timeout is applied on the **client** rather than left to the caller wrapping
    the call in ``asyncio.wait_for``: that wrapper only works when the call yields
    control at an await point, and it silently does nothing for a synchronous
    blocking call — which is exactly how this used to hang. See change
    ``fix-embedding-timeout-blocking`` design D1.

    Note: ``timeout`` is LangChain's *alias* for the ``request_timeout`` field, so the
    resulting instance exposes it as ``.request_timeout`` (there is no ``.timeout``
    attribute). Assert on ``request_timeout`` in tests.
    """
    provider = (_env("EMBEDDING_PROVIDER") or get_model_provider()).strip().lower()
    request_timeout = resolve_embedding_timeout(timeout)

    if provider == "azure":
        return AzureOpenAIEmbeddings(
            azure_deployment=_env("AZURE_OPENAI_DEPLOYMENT_EMBEDDING"),
            api_key=SecretStr(_env("AZURE_OPENAI_API_KEY", "") or ""),
            api_version=_env("AZURE_OPENAI_EMBEDDING_VERSION", "2023-05-15"),
            azure_endpoint=_env("AZURE_OPENAI_ENDPOINT_EMBEDDING"),
            timeout=request_timeout,
        )

    if provider in EMBEDDING_PROVIDERS:
        return OpenAIEmbeddings(
            model=_env("EMBEDDING_MODEL", "text-embedding-v3") or "text-embedding-v3",
            api_key=SecretStr(_env("EMBEDDING_API_KEY") or _env("LLM_API_KEY", "") or ""),
            base_url=_env("EMBEDDING_BASE_URL") or _env("LLM_BASE_URL"),
            # OpenAI-compatible providers like DashScope (Qwen) only accept raw
            # strings; disable token-id batching to send plain text.
            check_embedding_ctx_length=False,
            timeout=request_timeout,
        )

    raise ValueError(
        f"Unsupported EMBEDDING_PROVIDER={provider!r}. "
        "Use azure, qwen, zhipu, openai, or openai-compatible."
    )