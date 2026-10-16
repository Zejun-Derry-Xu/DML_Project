import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from app.domain.models import ReturnCase
from app.extractors.base import ExtractorError
from app.extractors.ollama import OllamaExtractor


@pytest.mark.asyncio
async def test_invalid_semantics_or_json_is_not_retried(monkeypatch):
    calls = []

    async def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "not json"}})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    extractor = OllamaExtractor(
        base_url="http://model/v1", model="test", timeout_seconds=1, retries=1
    )
    with pytest.raises(ExtractorError):
        await extractor.extract("Hello", ReturnCase(session_id=uuid4()), None)
    assert len(calls) == 1
    assert calls[0]["options"] == {"temperature": 0, "num_ctx": 4096, "num_predict": 512}


@pytest.mark.asyncio
async def test_total_budget_cancels_slow_transport(monkeypatch):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        await asyncio.sleep(2)
        return httpx.Response(200, json={})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    extractor = OllamaExtractor(
        base_url="http://model/v1", model="test", timeout_seconds=0.02, retries=1
    )
    with pytest.raises(ExtractorError):
        await asyncio.wait_for(extractor.extract("Hi", ReturnCase(session_id=uuid4()), None), 0.5)
    assert calls == 1


@pytest.mark.asyncio
async def test_transient_connection_failure_retries_once(monkeypatch):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("transient", request=request)
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": '{"answer_state":"stated",'
                    '"facts":{"used":{"value":false,"evidence":"E0"}}}'
                }
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    extractor = OllamaExtractor(
        base_url="http://model/v1", model="test", timeout_seconds=1, retries=9
    )
    facts = await extractor.extract("No.", ReturnCase(session_id=uuid4()), "used")
    assert facts.used is False and calls == 2
