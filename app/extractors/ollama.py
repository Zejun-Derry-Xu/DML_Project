import asyncio
import json
from time import monotonic

import httpx
from pydantic import ValidationError

from app.domain.models import ReturnCase, ReturnFacts
from app.extractors.base import ExtractorError
from app.extractors.compact import VERSION, prompt, schema, validate
from app.extractors.openai_compatible import OpenAICompatibleExtractor


class OllamaExtractor(OpenAICompatibleExtractor):
    """Grounded extraction; retries only transient transport errors within one budget."""

    variant = "focused"

    async def extract(
        self,
        message: str,
        current_case: ReturnCase,
        pending_question: str | None,
    ) -> ReturnFacts:
        self.last_diagnostics: dict[str, object] = {"spec_version": VERSION, "attempts": 0}
        self.last_trace: dict[str, object] = {}
        self.last_usage: dict[str, int] = {}
        root_url = self.base_url.removesuffix("/v1")
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "messages": [
                {
                    "role": "system",
                    "content": "Extract grounded facts, never decide return eligibility.",
                },
                {
                    "role": "user",
                    "content": prompt(message, current_case, pending_question),
                },
            ],
            "format": schema(pending_question, current_case.item_category == "apparel", message),
            "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 512},
        }
        deadline = monotonic() + self.timeout_seconds
        last_error: Exception | None = None
        for attempt in range(min(self.retries, 1) + 1):
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            self.last_diagnostics["attempts"] = attempt + 1
            try:
                async with asyncio.timeout(remaining):
                    async with httpx.AsyncClient(timeout=remaining) as client:
                        response = await client.post(f"{root_url}/api/chat", json=payload)
                        response.raise_for_status()
                    body = response.json()
                    if not isinstance(body, dict):
                        raise ValueError("Expected response object")
                    if body.get("done_reason") == "length":
                        raise ValueError("Truncated structured response")
                    self.last_usage = {
                        key: int(body[key])
                        for key in ("prompt_eval_count", "eval_count", "load_duration")
                        if key in body
                    }
                    facts, diagnostics, trace = validate(
                        json.loads(body["message"]["content"]),
                        message,
                        current_case,
                        pending_question,
                    )
                    self.last_diagnostics.update(diagnostics)
                    self.last_trace = trace
                    return facts
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if attempt < min(self.retries, 1):
                    await asyncio.sleep(min(0.25, max(0, deadline - monotonic())))
            except (
                httpx.HTTPError,
                TimeoutError,
                KeyError,
                TypeError,
                ValidationError,
                ValueError,
            ) as exc:
                last_error = exc
                break
        raise ExtractorError(
            "Ollama could not produce grounded facts within budget."
        ) from last_error
