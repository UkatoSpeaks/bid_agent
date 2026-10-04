"""GroqLLMClient tests against a mocked Groq SDK client. No network."""

import json
from types import SimpleNamespace

import groq
import httpx
import pytest
from pydantic import BaseModel, Field

from app.llm import (
    LLMConfigError,
    LLMRateLimitError,
    LLMResponseError,
    LLMUnavailableError,
)
from app.llm.cache import ResponseCache
from app.llm.groq_client import GroqLLMClient
from app.llm.schema import strict_json_schema


class Item(BaseModel):
    name: str
    count: int = Field(ge=0)
    note: str | None = None


class Basket(BaseModel):
    items: list[Item]


class MockGroq:
    """Stands in for groq.Groq: replies in order, raising any exceptions."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.requests.append(request)
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def rate_limit_error(retry_after=None):
    headers = {"retry-after": retry_after} if retry_after else {}
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(429, headers=headers, request=request)
    return groq.RateLimitError("rate limited", response=response, body=None)


def make_client(replies, cache=None, sleeps=None):
    mock = MockGroq(replies)
    client = GroqLLMClient(
        api_key=None,
        model="test-model",
        cache=cache,
        client=mock,
        sleep=(sleeps if sleeps is not None else []).append,
    )
    return client, mock


GOOD = {"name": "duct", "count": 3, "note": None}


def test_request_uses_json_schema_structured_output():
    client, mock = make_client([GOOD])

    result = client.structured("How many?", Item)

    assert result == Item(name="duct", count=3)
    request = mock.requests[0]
    assert request["model"] == "test-model"
    assert request["messages"] == [{"role": "user", "content": "How many?"}]
    assert request["temperature"] == 0.2
    assert request["reasoning_effort"] == "medium"
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["name"] == "Item"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["response_format"]["json_schema"]["schema"] == strict_json_schema(Item)
    assert "stream" not in request and "tools" not in request


def test_strict_schema_requires_every_field_and_forbids_extras():
    schema = strict_json_schema(Basket)

    assert schema["required"] == ["items"]
    assert schema["additionalProperties"] is False
    item = schema["$defs"]["Item"]
    # `note` has a default, but strict mode needs it listed as required.
    assert item["required"] == ["name", "count", "note"]
    assert item["additionalProperties"] is False
    assert "default" not in item["properties"]["note"]
    assert "title" not in item


def test_validation_failure_retries_once_with_the_error_in_the_prompt():
    bad = {"name": "duct", "count": -1, "note": None}  # count must be >= 0
    client, mock = make_client([bad, GOOD])

    result = client.structured("How many?", Item)

    assert result.count == 3
    assert len(mock.requests) == 2
    retry_prompt = mock.requests[1]["messages"][0]["content"]
    assert retry_prompt.startswith("How many?")
    assert "greater than or equal to 0" in retry_prompt


def test_invalid_json_also_triggers_the_retry():
    client, mock = make_client(["this is not json", GOOD])

    assert client.structured("How many?", Item).name == "duct"
    assert len(mock.requests) == 2


def test_second_validation_failure_raises_a_clear_error():
    bad = {"name": "duct", "count": -1, "note": None}
    client, mock = make_client([bad, bad])

    with pytest.raises(LLMResponseError, match="did not return a valid Item after 2 attempts"):
        client.structured("How many?", Item)
    assert len(mock.requests) == 2


def test_cache_hit_skips_the_api(tmp_path):
    cache = ResponseCache(tmp_path / "llm")
    client, mock = make_client([GOOD], cache=cache)

    first = client.structured("How many?", Item)
    second = client.structured("How many?", Item)  # MockGroq has no second reply

    assert first == second
    assert len(mock.requests) == 1
    files = list((tmp_path / "llm").glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8")) == GOOD


def test_cache_key_depends_on_prompt_schema_and_model(tmp_path):
    cache = ResponseCache(tmp_path / "llm")
    client, mock = make_client([GOOD, GOOD, {"items": [GOOD]}], cache=cache)

    client.structured("How many?", Item)
    client.structured("How many ducts?", Item)  # different prompt
    client.structured("How many?", Basket)  # different schema
    assert len(mock.requests) == 3

    other_model = GroqLLMClient(
        api_key=None, model="other-model", cache=cache, client=MockGroq([GOOD])
    )
    other_model.structured("How many?", Item)
    assert len(list((tmp_path / "llm").glob("*.json"))) == 4


def test_cache_key_depends_on_temperature_and_reasoning_effort(tmp_path):
    cache = ResponseCache(tmp_path / "llm")

    def ask(**settings):
        mock = MockGroq([GOOD])
        client = GroqLLMClient(
            api_key=None, model="test-model", cache=cache, client=mock, **settings
        )
        client.structured("How many?", Item)
        return len(mock.requests)

    assert ask() == 1  # temperature 0.2, reasoning effort "medium"
    assert ask() == 0  # same settings: served from the cache
    assert ask(temperature=0.0) == 1
    assert ask(reasoning_effort="high") == 1
    assert ask(reasoning_effort=None) == 1
    assert ask(temperature=0.0) == 0
    assert len(list((tmp_path / "llm").glob("*.json"))) == 4


def test_retried_response_is_cached_under_the_original_prompt(tmp_path):
    cache = ResponseCache(tmp_path / "llm")
    bad = {"name": "duct", "count": -1, "note": None}
    client, mock = make_client([bad, GOOD], cache=cache)

    client.structured("How many?", Item)
    client.structured("How many?", Item)

    assert len(mock.requests) == 2  # bad + retry; the second call is a cache hit


def test_failed_responses_are_not_cached(tmp_path):
    cache = ResponseCache(tmp_path / "llm")
    bad = {"name": "duct", "count": -1, "note": None}
    client, _ = make_client([bad, bad], cache=cache)

    with pytest.raises(LLMResponseError):
        client.structured("How many?", Item)
    assert not list((tmp_path / "llm").glob("*.json"))


def test_without_a_cache_every_call_reaches_the_api():
    client, mock = make_client([GOOD, GOOD], cache=None)

    client.structured("How many?", Item)
    client.structured("How many?", Item)

    assert len(mock.requests) == 2


def test_rate_limit_backs_off_exponentially_then_succeeds():
    sleeps = []
    client, mock = make_client([rate_limit_error(), rate_limit_error(), GOOD], sleeps=sleeps)

    assert client.structured("How many?", Item).count == 3
    assert len(mock.requests) == 3
    assert sleeps == [2.0, 4.0]


def test_rate_limit_honours_a_longer_retry_after_header():
    sleeps = []
    client, _ = make_client([rate_limit_error(retry_after="17"), GOOD], sleeps=sleeps)

    client.structured("How many?", Item)

    assert sleeps == [17.0]


def test_rate_limit_gives_up_after_four_attempts():
    sleeps = []
    client, mock = make_client([rate_limit_error() for _ in range(4)], sleeps=sleeps)

    with pytest.raises(LLMRateLimitError, match="after 4 attempts"):
        client.structured("How many?", Item)
    assert len(mock.requests) == 4
    assert sleeps == [2.0, 4.0, 8.0]


def test_a_connection_error_is_reported_as_the_provider_being_unavailable():
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    client, _mock = make_client([groq.APIConnectionError(request=request)])

    with pytest.raises(LLMUnavailableError, match="could not be reached"):
        client.structured("How many?", Item)


def test_usage_adds_up_calls_tokens_and_rate_limit_waits(tmp_path):
    class MockGroqWithUsage(MockGroq):
        def _create(self, **request):
            response = super()._create(**request)
            response.usage = SimpleNamespace(
                prompt_tokens=100, completion_tokens=20, total_tokens=120
            )
            return response

    mock = MockGroqWithUsage([rate_limit_error(), GOOD, GOOD])
    client = GroqLLMClient(
        api_key=None,
        model="test-model",
        cache=ResponseCache(tmp_path),
        client=mock,
        sleep=lambda _seconds: None,
    )

    client.structured("How many?", Item)
    client.structured("How many more?", Item)
    client.structured("How many?", Item)  # served from the cache: not counted

    usage = client.usage
    assert usage.calls == 2
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (200, 40, 240)
    assert usage.rate_limit_waits == 1
    assert usage.rate_limit_wait_seconds == 2.0


def test_usage_stays_zero_when_the_provider_reports_none():
    client, _mock = make_client([GOOD])

    client.structured("How many?", Item)

    assert client.usage.calls == 1
    assert client.usage.total_tokens == 0


def test_missing_api_key_raises_a_clear_error():
    with pytest.raises(LLMConfigError, match="GROQ_API_KEY"):
        GroqLLMClient(api_key=None, model="test-model")
