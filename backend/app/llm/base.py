"""Provider-agnostic LLM interface.

The rest of the app depends only on LLMClient. Provider SDKs are imported
solely inside this package (see groq_client.py).
"""

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Base class for every error raised by an LLMClient."""


class LLMConfigError(LLMError):
    """The client cannot be built, e.g. the API key is missing."""


class LLMRateLimitError(LLMError):
    """The provider kept returning HTTP 429 after all retry attempts."""


class LLMResponseError(LLMError):
    """The model's output did not validate against the schema, even after a retry."""


class LLMClient(ABC):
    @abstractmethod
    def structured(self, prompt: str, schema: type[T]) -> T:
        """Send `prompt` and return the reply validated as an instance of `schema`.

        Raises LLMResponseError if the reply cannot be validated and
        LLMRateLimitError if the provider keeps rate limiting the request.
        """
