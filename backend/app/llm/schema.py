"""JSON schema generation for structured outputs.

Strict structured-output modes (Groq, OpenAI) require every object to list
all of its properties as `required` and to set `additionalProperties: false`.
Optional fields are expressed as nullable (`anyOf: [..., {"type": "null"}]`),
which is what Pydantic already emits for `X | None`.
"""

from typing import Any

from pydantic import BaseModel

# Annotations that carry no meaning for the model.
_DROPPED_KEYS = ("default", "title")
# Keywords whose values map names (fields, definitions) to schemas.
_NAME_MAPS = ("properties", "$defs")


def strict_json_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema, adjusted to satisfy strict structured outputs."""
    return _strictify(schema.model_json_schema())


def _strictify(node: Any) -> Any:
    if isinstance(node, list):
        return [_strictify(item) for item in node]
    if not isinstance(node, dict):
        return node

    result: dict[str, Any] = {}
    for key, value in node.items():
        if key in _DROPPED_KEYS:
            continue
        if key in _NAME_MAPS:
            # Keys are names here, not keywords: a field may be called "title".
            result[key] = {name: _strictify(sub) for name, sub in value.items()}
        else:
            result[key] = _strictify(value)

    if result.get("type") == "object":
        result["required"] = list(result.get("properties", {}))
        result["additionalProperties"] = False
    return result
