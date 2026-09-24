import asyncio

import httpx
from pydantic import ValidationError

from app.domain.models import ReturnCase, ReturnFacts
from app.extractors.base import ExtractorError
from app.extractors.openai_compatible import (
    SYSTEM_PROMPT,
    OpenAICompatibleExtractor,
    extraction_prompt,
)


class OllamaExtractor(OpenAICompatibleExtractor):
    """Use Ollama's native API so Qwen thinking can be disabled explicitly."""

    async def extract(
        self,
        message: str,
        current_case: ReturnCase,
        pending_question: str | None,
    ) -> ReturnFacts:
        root_url = self.base_url.removesuffix("/v1")
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": extraction_prompt(message, current_case, pending_question),
                },
            ],
            "format": ReturnFacts.model_json_schema(),
            "options": {"temperature": 0, "num_predict": 300},
        }
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(f"{root_url}/api/chat", json=payload)
                    response.raise_for_status()
                content = response.json()["message"]["content"]
                return ReturnFacts.model_validate_json(content)
            except (httpx.HTTPError, KeyError, TypeError, ValidationError, ValueError) as exc:
                last_error = exc
                if attempt < self.retries:
                    await asyncio.sleep(0.25 * (attempt + 1))
        raise ExtractorError("Ollama did not return valid facts.") from last_error
