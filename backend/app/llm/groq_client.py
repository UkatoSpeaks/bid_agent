"""Groq implementation of LLMClient, using Structured Outputs (json_schema).

No streaming and no tool calls: Groq does not support either together with
structured outputs. See https://console.groq.com/docs/structured-outputs
"""

import logging
import time
from collections.abc import Callable
from typing import Any

import groq
from pydantic import ValidationError

from app.llm.base import (
    LLMClient,
    LLMConfigError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMUnavailableError,
    LLMUsage,
    T,
)
from app.llm.cache import ResponseCache, cache_key
from app.llm.schema import strict_json_schema

logger = logging.getLogger(__name__)

MAX_RATE_LIMIT_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 60.0

_RETRY_TEMPLATE = """{prompt}

Your previous reply was rejected because it did not match the required schema:
{error}
Reply again with JSON that fixes this problem."""


class GroqLLMClient(LLMClient):
    def __init__(
        self,
        api_key: str | None,
        model: str,
        *,
        temperature: float = 0.2,
        reasoning_effort: str | None = "medium",
        cache: ResponseCache | None = None,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """`client` and `sleep` exist so tests can inject fakes."""
        if client is None:
            if not api_key:
                raise LLMConfigError(
                    "GROQ_API_KEY is not set. Add it to .env (see .env.example)."
                )
            # Retries are handled here, so the SDK's own are switched off.
            client = groq.Groq(api_key=api_key, max_retries=0)
        self._client = client
        self._model = model
        self._temperature = temperature
        self._reasoning_effort = reasoning_effort
        self._cache = cache
        self._sleep = sleep
        self.usage = LLMUsage()

    def structured(self, prompt: str, schema: type[T]) -> T:
        json_schema = strict_json_schema(schema)
        key = cache_key(
            self._model, prompt, json_schema, self._temperature, self._reasoning_effort
        )

        if self._cache is not None:
            cached = self._cache.get(key)
            if cached is not None:
                try:
                    return schema.model_validate(cached)
                except ValidationError:
                    logger.warning("Ignoring invalid LLM cache entry %s", key)

        result = self._complete_validated(prompt, schema, json_schema)
        if self._cache is not None:
            self._cache.set(key, result.model_dump(mode="json"))
        return result

    def _complete_validated(
        self, prompt: str, schema: type[T], json_schema: dict[str, Any]
    ) -> T:
        """Ask once; on a validation failure ask once more, quoting the error."""
        try:
            return self._complete(prompt, schema, json_schema)
        except _InvalidOutput as first:
            logger.warning("LLM output failed validation, retrying once: %s", first)
            retry_prompt = _RETRY_TEMPLATE.format(prompt=prompt, error=first)
            try:
                return self._complete(retry_prompt, schema, json_schema)
            except _InvalidOutput as second:
                raise LLMResponseError(
                    f"{self._model} did not return a valid {schema.__name__} "
                    f"after 2 attempts. Last error: {second}"
                ) from second

    def _complete(self, prompt: str, schema: type[T], json_schema: dict[str, Any]) -> T:
        request: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": json_schema,
                },
            },
        }
        if self._reasoning_effort:
            request["reasoning_effort"] = self._reasoning_effort

        try:
            response = self._with_backoff(request)
        except groq.BadRequestError as exc:
            # Groq answers 400 json_validate_failed when the model's output
            # does not match the schema; treat it like any validation failure.
            if "json_validate_failed" in str(exc):
                raise _InvalidOutput(str(exc)) from exc
            raise LLMError(f"Groq rejected the request: {exc}") from exc
        except (groq.APIConnectionError, groq.InternalServerError) as exc:
            raise LLMUnavailableError(f"Groq could not be reached: {exc}") from exc
        except groq.APIError as exc:
            raise LLMError(f"Groq request failed: {exc}") from exc

        self._record_usage(response)
        content = response.choices[0].message.content or ""
        try:
            return schema.model_validate_json(content)
        except ValidationError as exc:
            raise _InvalidOutput(str(exc)) from exc

    def _with_backoff(self, request: dict[str, Any]) -> Any:
        """Call the API, backing off exponentially on HTTP 429."""
        for attempt in range(1, MAX_RATE_LIMIT_ATTEMPTS + 1):
            try:
                return self._client.chat.completions.create(**request)
            except groq.RateLimitError as exc:
                if attempt == MAX_RATE_LIMIT_ATTEMPTS:
                    raise LLMRateLimitError(
                        f"Groq rate limit still exceeded after "
                        f"{MAX_RATE_LIMIT_ATTEMPTS} attempts: {exc}"
                    ) from exc
                delay = _backoff_delay(attempt, exc)
                logger.warning(
                    "Groq rate limit hit (attempt %d/%d), waiting %.1fs",
                    attempt,
                    MAX_RATE_LIMIT_ATTEMPTS,
                    delay,
                )
                self.usage.rate_limit_waits += 1
                self.usage.rate_limit_wait_seconds += delay
                self._sleep(delay)
        raise AssertionError("unreachable")

    def _record_usage(self, response: Any) -> None:
        """Add one reply's token counts to `usage`, if Groq reported them."""
        self.usage.calls += 1
        reported = getattr(response, "usage", None)
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            count = getattr(reported, field, None)
            if isinstance(count, int):
                setattr(self.usage, field, getattr(self.usage, field) + count)


class _InvalidOutput(Exception):
    """The model replied, but not with JSON that validates against the schema."""


def _backoff_delay(attempt: int, exc: Exception) -> float:
    """2s, 4s, 8s ... or the server's Retry-After if that is longer."""
    delay = BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
    response = getattr(exc, "response", None)
    retry_after = getattr(response, "headers", {}).get("retry-after")
    try:
        delay = max(delay, float(retry_after))
    except (TypeError, ValueError):
        pass
    return min(delay, BACKOFF_MAX_SECONDS)
