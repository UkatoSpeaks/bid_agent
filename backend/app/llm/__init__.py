"""LLM access. Import LLMClient from here; never import a provider SDK elsewhere."""

from app.config import Settings, get_settings
from app.llm.base import (
    LLMClient,
    LLMConfigError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
)

__all__ = [
    "LLMClient",
    "LLMConfigError",
    "LLMError",
    "LLMRateLimitError",
    "LLMResponseError",
    "get_llm_client",
]


def get_llm_client(settings: Settings | None = None) -> LLMClient:
    """Build the configured LLM client (Groq is the only provider for now)."""
    # Imported lazily so the provider SDK is only loaded when a client is built.
    from app.llm.cache import ResponseCache
    from app.llm.groq_client import GroqLLMClient

    settings = settings or get_settings()
    cache = ResponseCache(settings.resolved_llm_cache_dir) if settings.llm_cache else None
    return GroqLLMClient(
        api_key=settings.groq_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        reasoning_effort=settings.llm_reasoning_effort,
        cache=cache,
    )
