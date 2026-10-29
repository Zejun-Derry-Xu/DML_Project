"""Provider visibility probe. This never runs a completion (inference_tested stays false)."""

from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import Settings
from app.extractors.dashscope import listed_model_ids, models_url, resolved_base_url, resolved_model


def _public_base_url(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.username or parts.password or not parts.scheme or not parts.netloc:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


async def probe_model(settings: Settings) -> dict[str, Any]:
    if settings.llm_provider == "dashscope":
        return await _probe_dashscope(settings)
    if settings.llm_provider == "ollama":
        return await _probe_ollama(settings)
    return {
        "status": "unavailable",
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "inference_tested": False,
    }


async def _probe_ollama(settings: Settings) -> dict[str, Any]:
    url = settings.llm_base_url.removesuffix("/v1").rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            result = await client.get(url)
            result.raise_for_status()
            models = result.json().get("models", [])
        model = next((item for item in models if item.get("name") == settings.llm_model), None)
        return {
            "status": "available" if model else "missing_model",
            "provider": "ollama",
            "model": settings.llm_model,
            "digest": model.get("digest") if model else None,
            "inference_tested": False,
        }
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
        return {
            "status": "unavailable",
            "provider": "ollama",
            "model": settings.llm_model,
            "inference_tested": False,
        }


async def _probe_dashscope(settings: Settings) -> dict[str, Any]:
    model = resolved_model(settings)
    base_url = _public_base_url(resolved_base_url(settings))
    body: dict[str, Any] = {
        "provider": "dashscope",
        "model": model,
        "base_url": base_url,
        "digest": None,
        "inference_tested": False,
    }
    if not settings.dashscope_api_key.strip():
        body["status"] = "unavailable"
        body["reason"] = "missing_api_key"
        return body
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            result = await client.get(
                models_url(settings),
                headers={"Authorization": f"Bearer {settings.dashscope_api_key}"},
            )
        if result.status_code in {401, 403}:
            body["status"] = "unavailable"
            body["reason"] = "auth_rejected"
            return body
        result.raise_for_status()
        listed = listed_model_ids(result.json())
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
        body["status"] = "unavailable"
        return body
    if listed is None:
        body["status"] = "unavailable"
        return body
    if model not in listed:
        body["status"] = "missing_model"
        return body
    body["status"] = "available"
    return body
