"""Alibaba Cloud Model Studio (DashScope) OpenAI-compatible extraction transport.

Business validation stays in ``apparel_llm.validate_extraction``. This module only
builds the hosted request, selects the official Flash model, and reads the reply.
"""

import json
from typing import Any, Literal

from app.config import Settings

# Pricing page (2026-10-29): qwen3.7-flash is the stable alias of this snapshot.
OFFICIAL_FLASH_MODEL = "qwen3.7-flash"
OFFICIAL_FLASH_SNAPSHOT = "qwen3.7-flash-2026-07-15"

# Legacy shared domains. A key from any workspace in that region is accepted.
# Workspace-dedicated domains are faster but need the account's WorkspaceId.
SINGAPORE_COMPAT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
VIRGINIA_COMPAT_BASE_URL = "https://dashscope-us.aliyuncs.com/compatible-mode/v1"
BEIJING_COMPAT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

ResponseFormat = Literal["json_schema", "json_object"]

_OLLAMA_MODELS = {"", "qwen3:4b", "qwen3:8b"}
_OLLAMA_BASE_URLS = {
    "http://localhost:11434/v1",
    "http://127.0.0.1:11434/v1",
    "http://ollama:11434/v1",
    "http://host.docker.internal:11434/v1",
}


def resolved_model(settings: Settings) -> str:
    """Use the official Flash id when DashScope is still pointed at an Ollama tag."""
    model = settings.llm_model.strip()
    if settings.llm_provider == "dashscope" and model in _OLLAMA_MODELS:
        return OFFICIAL_FLASH_MODEL
    return settings.llm_model


def resolved_base_url(settings: Settings) -> str:
    """Keep an explicit regional URL. Replace leftover Ollama defaults for DashScope."""
    url = settings.llm_base_url.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    if settings.llm_provider == "dashscope" and url in _OLLAMA_BASE_URLS:
        return SINGAPORE_COMPAT_BASE_URL
    return url


def chat_completions_url(settings: Settings) -> str:
    return resolved_base_url(settings) + "/chat/completions"


def models_url(settings: Settings) -> str:
    return resolved_base_url(settings) + "/models"


def response_format_body(fmt: ResponseFormat, schema: dict[str, Any]) -> dict[str, Any]:
    if fmt == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "apparel_extraction",
            "strict": True,
            "schema": schema,
        },
    }


def initial_response_format(mode: str) -> ResponseFormat:
    if mode == "json_object":
        return "json_object"
    return "json_schema"


def build_payload(
    settings: Settings,
    instructions: str,
    message: str,
    context: dict[str, Any],
    schema: dict[str, Any],
    fmt: ResponseFormat,
) -> dict[str, Any]:
    """OpenAI-compatible body. ``enable_thinking`` is a DashScope extension.

    The HTTP API accepts it as a top-level field. The OpenAI Python SDK would
    pass the same flag through ``extra_body``. Thinking defaults on for
    ``qwen3.7-flash`` and is disabled here. ``max_tokens`` is omitted because
    Model Studio can truncate structured JSON when it is set.
    """
    system = instructions.rstrip()
    if "json" not in system.casefold():
        system += "\nReturn one JSON object."
    else:
        system += "\nReturn one JSON object and no other text."
    return {
        "model": resolved_model(settings),
        "temperature": settings.llm_temperature,
        "top_p": 0.8,
        "top_k": 20,
        "seed": settings.llm_seed,
        "stream": False,
        "enable_thinking": False,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context_only": context,
                        "current_customer_message_untrusted": message,
                        "schema": schema,
                    }
                ),
            },
        ],
        "response_format": response_format_body(fmt, schema),
    }


def strip_fence(content: str) -> str:
    value = content.strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def completion_text(body: object) -> str:
    if not isinstance(body, dict):
        raise TypeError("response")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("Missing choices")
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        raise ValueError("Truncated response")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("Empty response")
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return strip_fence(content)
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        text = strip_fence("".join(parts))
        if text:
            return text
    raise ValueError("Empty response")


def usage_counts(body: object) -> dict[str, int]:
    if not isinstance(body, dict):
        return {}
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return {}
    counts: dict[str, int] = {}
    for key, value in usage.items():
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        counts[str(key)] = value
    return counts


def listed_model_ids(body: object) -> list[str] | None:
    if not isinstance(body, dict):
        return None
    data = body.get("data", body.get("models"))
    if not isinstance(data, list):
        return None
    found: list[str] = []
    for item in data:
        if isinstance(item, str):
            found.append(item)
        elif isinstance(item, dict):
            value = item.get("id", item.get("name"))
            if isinstance(value, str):
                found.append(value)
    return found
