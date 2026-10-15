import asyncio
from time import monotonic

import httpx
from pydantic import ValidationError

from app.domain.models import ReturnCase, ReturnFacts
from app.extractors.base import ExtractorError
from app.extractors.contracts import SPEC_VERSION, EvidenceFacts, grounded, output_schema, prompt
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
        self.last_diagnostics: dict[str, object] = {"spec_version": SPEC_VERSION, "attempts": 0}
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
                    "content": prompt(
                        message, current_case, pending_question, focused=self.variant == "focused"
                    ),
                },
            ],
            "format": output_schema(pending_question),
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
                    if body.get("done_reason") == "length":
                        raise ValueError("Truncated structured response")
                    self.last_usage = {
                        key: int(body[key])
                        for key in ("prompt_eval_count", "eval_count", "load_duration")
                        if key in body
                    }
                    envelope = EvidenceFacts.model_validate_json(body["message"]["content"])
                    facts, rejected = grounded(envelope, message, pending_question)
                    self.last_diagnostics["rejected_fields"] = rejected
                    self.last_diagnostics["evidence_spans"] = {
                        key: [message.find(quote), message.find(quote) + len(quote)]
                        for key, quote in envelope.evidence.items()
                        if key in ReturnFacts.model_fields and quote and quote in message
                    }
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
