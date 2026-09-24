import json
from uuid import uuid4

import httpx
import pytest

from app.domain.models import ReturnCase
from app.extractors.ollama import OllamaExtractor
from app.extractors.openai_compatible import extraction_prompt


def test_extraction_prompt_separates_message_from_known_facts() -> None:
    case = ReturnCase(
        session_id=uuid4(),
        order_number="ORD-1001",
        item_name="Trail Shoes",
    )

    prompt = extraction_prompt("They are unopened.", case, "Was the package opened?")

    assert "CUSTOMER MESSAGE" in prompt
    assert "They are unopened." in prompt
    assert "KNOWN CASE FACTS (context only; do not copy" in prompt
    assert "ORD-1001" in prompt


@pytest.mark.asyncio
async def test_ollama_uses_native_structured_chat_without_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": (
                        '{"intent":"return","order_id":"ORD-1001","item_name":null,'
                        '"reason":null,"used":null,"opened":false,"damaged":null,'
                        '"wants_human":false}'
                    )
                }
            },
        )

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def client_factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    extractor = OllamaExtractor(
        base_url="http://localhost:11434/v1",
        model="qwen3:4b",
        api_key="",
        timeout_seconds=5,
        retries=0,
    )

    result = await extractor.extract(
        "Return ORD-1001; it is unopened.", ReturnCase(session_id=uuid4()), None
    )

    assert result.order_id == "ORD-1001"
    assert result.opened is False
    assert captured["think"] is False
    assert captured["stream"] is False
    assert captured["format"] == result.model_json_schema()
