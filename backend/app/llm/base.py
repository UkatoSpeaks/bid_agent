"""Provider-agnostic LLM interface.

The rest of the app depends only on LLMClient. Provider SDKs are imported
solely inside this package (see groq_client.py).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Base class for every error raised by an LLMClient."""


class LLMConfigError(LLMError):
    """The client cannot be built, e.g. the API key is missing."""


class LLMRateLimitError(LLMError):
    """The provider kept returning HTTP 429 after all retry attempts."""


class LLMUnavailableError(LLMError):
    """The provider could not be reached, timed out or had a server error.

    Unlike the other errors this says nothing about the request or the
    model's answer: the same call may work a moment later.
    """


class LLMResponseError(LLMError):
    """The model's output did not validate against the schema, even after a retry."""


@dataclass
class LLMUsage:
    """Running totals of what a client has sent to its provider.

    Token counts stay 0 if the provider does not report them. Replies served
    from the cache are not counted: they cost nothing.
    """

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    rate_limit_waits: int = 0
    rate_limit_wait_seconds: float = 0.0


class LLMClient(ABC):
    # Set by clients that measure their usage (see groq_client.py).
    usage: LLMUsage | None = None

    @abstractmethod
    def structured(self, prompt: str, schema: type[T]) -> T:
        """Send `prompt` and return the reply validated as an instance of `schema`.

        Raises LLMResponseError if the reply cannot be validated and
        LLMRateLimitError if the provider keeps rate limiting the request.
        """
