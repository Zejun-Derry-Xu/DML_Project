import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.extractors.apparel_llm import LLMFactExtractor
from app.extractors.base import ExtractorError
from app.extractors.dashscope import (
    OFFICIAL_FLASH_MODEL,
    SINGAPORE_COMPAT_BASE_URL,
    resolved_base_url,
    resolved_model,
)
from app.extractors.model_status import probe_model
from app.main import create_app
from scripts.smoke_dashscope import run_smoke

SECRET = "super-secret-key"
MESSAGE = "I want to return this shirt because it is too loose."


def hosted(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "extraction_mode": "llm",
        "llm_provider": "dashscope",
        "llm_model": "qwen3:4b",
        "llm_base_url": "http://ollama:11434/v1",
        "dashscope_api_key": SECRET,
        "llm_timeout_seconds": 5,
        "dashscope_response_format": "auto",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def valid_content() -> str:
    return json.dumps(
        {
            "intent": "return",
            "intent_evidence": "return this shirt",
            "facts": [
                {
                    "field": "reason_text",
                    "value": "too loose",
                    "state": "stated",
                    "evidence": "too loose",
                }
            ],
            "checklist_reply": {
                "kind": "none",
                "evidence": "",
                "submit_requested": False,
                "submit_evidence": "",
                "policy_question": "",
                "topics": [],
            },
        }
    )


def completion(content: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "choices": [
                {"finish_reason": "stop", "message": {"role": "assistant", "content": content}}
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        },
    )


def install(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    original = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def test_dashscope_defaults_replace_ollama_tag_and_url() -> None:
    settings = hosted()
    assert resolved_model(settings) == OFFICIAL_FLASH_MODEL
    assert resolved_base_url(settings) == SINGAPORE_COMPAT_BASE_URL
    explicit = hosted(
        llm_model="qwen3.7-flash-2026-07-15",
        llm_base_url="https://dashscope-us.aliyuncs.com/compatible-mode/v1",
    )
    assert resolved_model(explicit) == "qwen3.7-flash-2026-07-15"
    assert resolved_base_url(explicit) == "https://dashscope-us.aliyuncs.com/compatible-mode/v1"
    assert resolved_model(Settings(llm_provider="ollama", llm_model="qwen3:4b")) == "qwen3:4b"


@pytest.mark.asyncio
async def test_dashscope_success_disables_thinking_and_hides_the_key(monkeypatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return completion(valid_content())

    install(monkeypatch, handler)
    extractor = LLMFactExtractor(hosted(), capture_diagnostics=True)
    result = await extractor.extract(MESSAGE, {"target": "reason_text"})

    assert result.intent == "return"
    assert result.facts[0].value == "too loose"
    assert extractor.last_usage["total_tokens"] == 18
    body = json.loads(seen[0].content)
    assert str(seen[0].url) == SINGAPORE_COMPAT_BASE_URL + "/chat/completions"
    assert seen[0].headers["authorization"] == f"Bearer {SECRET}"
    assert body["model"] == OFFICIAL_FLASH_MODEL
    assert body["enable_thinking"] is False
    assert body["response_format"]["type"] == "json_schema"
    assert "json" in body["messages"][0]["content"].casefold()
    dumped = json.dumps(extractor.last_trace)
    assert SECRET not in dumped
    assert SECRET not in seen[0].content.decode()


@pytest.mark.asyncio
async def test_dashscope_bad_json_does_not_retry(monkeypatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return completion("this is not json")

    install(monkeypatch, handler)
    with pytest.raises(ExtractorError):
        await LLMFactExtractor(hosted()).extract(MESSAGE, {})
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 503])
async def test_dashscope_retries_rate_limit_and_server_errors_then_degrades(
    monkeypatch, status_code: int
) -> None:
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path.endswith("/chat/completions"))
        return httpx.Response(status_code, json={"error": {"message": "busy"}})

    install(monkeypatch, handler)
    with pytest.raises(ExtractorError):
        await LLMFactExtractor(hosted()).extract(MESSAGE, {})
    assert seen == [True, True]


@pytest.mark.asyncio
async def test_dashscope_timeout_degrades_without_a_second_attempt(monkeypatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ReadTimeout("timed out", request=request)

    install(monkeypatch, handler)
    with pytest.raises(ExtractorError):
        await LLMFactExtractor(hosted()).extract(MESSAGE, {})
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_json_schema_http_400_falls_back_to_json_object(monkeypatch) -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body["response_format"])
        if body["response_format"]["type"] == "json_schema":
            return httpx.Response(
                400, json={"error": {"message": "Singapore models are not supported yet"}}
            )
        return completion(valid_content())

    install(monkeypatch, handler)
    extractor = LLMFactExtractor(hosted())
    result = await extractor.extract(MESSAGE, {})
    assert result.facts[0].field == "reason_text"
    assert [item["type"] for item in seen] == ["json_schema", "json_object"]
    assert extractor.last_trace["structured_output"] == "json_object_fallback"


@pytest.mark.asyncio
async def test_forced_json_object_does_not_call_json_schema(monkeypatch) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["response_format"]["type"])
        return completion(valid_content())

    install(monkeypatch, handler)
    await LLMFactExtractor(hosted(dashscope_response_format="json_object")).extract(MESSAGE, {})
    assert seen == ["json_object"]


@pytest.mark.asyncio
async def test_missing_key_does_not_call_the_network(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(request.url)

    install(monkeypatch, handler)
    extractor = LLMFactExtractor(hosted(dashscope_api_key=""))
    with pytest.raises(ExtractorError):
        await extractor.extract(MESSAGE, {})
    assert extractor.last_trace["stage"] == "auth"
    assert SECRET not in json.dumps(extractor.last_trace)


@pytest.mark.asyncio
async def test_model_status_lists_hosted_model_without_inference(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"data": [{"id": OFFICIAL_FLASH_MODEL}]})

    install(monkeypatch, handler)
    status = await probe_model(hosted())
    assert status["status"] == "available"
    assert status["model"] == OFFICIAL_FLASH_MODEL
    assert status["base_url"] == SINGAPORE_COMPAT_BASE_URL
    assert status["inference_tested"] is False
    assert SECRET not in json.dumps(status)


@pytest.mark.asyncio
async def test_model_status_reports_auth_and_missing_model(monkeypatch) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(401, json={"error": {"message": "bad key"}})
        return httpx.Response(200, json={"data": [{"id": "qwen-plus"}]})

    install(monkeypatch, handler)
    missing_key = await probe_model(hosted(dashscope_api_key=""))
    assert missing_key["reason"] == "missing_api_key"
    assert calls["n"] == 0
    rejected = await probe_model(hosted())
    assert rejected["status"] == "unavailable"
    assert rejected["reason"] == "auth_rejected"
    absent = await probe_model(hosted())
    assert absent["status"] == "missing_model"


@pytest.mark.asyncio
async def test_ollama_status_still_reads_tags(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen3:4b", "digest": "abc"}]})

    install(monkeypatch, handler)
    status = await probe_model(
        Settings(llm_provider="ollama", llm_model="qwen3:4b", llm_base_url="http://ollama:11434/v1")
    )
    assert status == {
        "status": "available",
        "provider": "ollama",
        "model": "qwen3:4b",
        "digest": "abc",
        "inference_tested": False,
    }


def test_model_status_route_uses_the_probe(monkeypatch) -> None:
    async def fake_probe(settings: Settings) -> dict[str, object]:
        assert settings.llm_provider == get_settings().llm_provider
        return {"status": "unavailable", "model": "qwen3.7-flash", "inference_tested": False}

    monkeypatch.setattr("app.main.probe_model", fake_probe)
    with TestClient(create_app()) as client:
        response = client.get("/model/status")
    assert response.status_code == 200
    assert response.json()["inference_tested"] is False
    assert response.json()["model"] == "qwen3.7-flash"


def test_live_smoke_skips_without_a_key(monkeypatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("live call")

    monkeypatch.setattr(httpx, "post", boom)
    assert run_smoke("") == 0
