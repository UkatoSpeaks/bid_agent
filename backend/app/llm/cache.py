"""On-disk cache of parsed LLM responses.

Keyed by everything that shapes the reply: model, prompt, schema, temperature
and reasoning effort.
"""

import hashlib
import json
from pathlib import Path
from typing import Any


def cache_key(
    model: str,
    prompt: str,
    schema: dict[str, Any],
    temperature: float,
    reasoning_effort: str | None,
) -> str:
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "schema": schema,
            "temperature": temperature,
            "reasoning_effort": reasoning_effort,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResponseCache:
    """One JSON file per response. A missing or corrupt file is a cache miss."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def get(self, key: str) -> Any | None:
        try:
            return json.loads(self._path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def set(self, key: str, value: Any) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path(key).write_text(
            json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"
