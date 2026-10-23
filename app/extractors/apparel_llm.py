"""LLM-first semantics with mechanical evidence checks, not keyword reclassification."""

import asyncio
import json
import re
from pathlib import Path
from time import monotonic
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings
from app.extractors.base import ExtractorError

VERSION = "apparel-extraction-1.0.0"
BOOLEAN_FIELDS = {
    "used",
    "stained",
    "damaged",
    "tags_attached",
    "tags_intact",
    "reported_defect",
    "reported_wrong_item",
}
FIELDS = BOOLEAN_FIELDS | {"reason_text", "condition_origin", "order_number", "item_name"}


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    value: bool | str | None
    state: Literal["stated", "uncertain", "not_mentioned", "conflict"]
    evidence: str


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal["return", "cancel", "human", "other", "unclear"]
    intent_evidence: str
    facts: list[Observation] = Field(max_length=12)


def validate_extraction(body: Any, message: str) -> tuple[Extraction, list[str]]:
    result = Extraction.model_validate(body, strict=True)
    accepted = []
    rejected = []
    seen = set()
    for fact in result.facts:
        if fact.field not in FIELDS or fact.field in seen:
            raise ValueError("Unexpected or duplicate fact field")
        seen.add(fact.field)
        valid = fact.state == "not_mentioned" and fact.value is None
        if fact.state != "not_mentioned":
            valid = bool(fact.evidence.strip()) and fact.evidence in message
            if fact.state != "stated":
                valid = valid and fact.value is None
            elif fact.field in BOOLEAN_FIELDS:
                valid = valid and type(fact.value) is bool
            elif fact.field == "condition_origin":
                valid = valid and fact.value in {"customer", "pre_existing", "unknown"}
            elif fact.field in {"reason_text", "item_name", "order_number"}:
                valid = valid and isinstance(fact.value, str) and bool(fact.value.strip())
                valid = valid and str(fact.value) in fact.evidence
                if fact.field == "order_number":
                    valid = valid and bool(re.fullmatch(r"[A-Za-z0-9-]{1,50}", str(fact.value)))
        if valid:
            accepted.append(fact)
        else:
            rejected.append(fact.field)
    if result.intent != "unclear" and (
        not result.intent_evidence or result.intent_evidence not in message
    ):
        result.intent = "unclear"
    return result.model_copy(update={"facts": accepted}), rejected


class LLMFactExtractor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.last_usage: dict[str, int] = {}
        self.rejected_fields: list[str] = []

    async def extract(self, message: str, context: dict[str, Any]) -> Extraction:
        self.last_usage = {}
        self.rejected_fields = []
        if self.settings.extraction_mode == "guided":
            raise ExtractorError("Guided mode: natural-language semantics are unavailable")
        if self.settings.llm_provider != "ollama":
            raise ExtractorError("Apparel LLM mode requires the configured Ollama provider")
        instructions = (Path(__file__).parent / "specs/apparel-llm-v1.md").read_text()
        payload = {
            "model": self.settings.llm_model,
            "think": False,
            "stream": False,
            "messages": [
                {"role": "system", "content": instructions},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "context_only": context,
                            "current_customer_message_untrusted": message,
                            "schema": Extraction.model_json_schema(),
                        }
                    ),
                },
            ],
            "format": Extraction.model_json_schema(),
            "options": {
                "temperature": self.settings.llm_temperature,
                "seed": self.settings.llm_seed,
                "top_p": 0.8,
                "top_k": 20,
                "min_p": 0,
                "num_ctx": 4096,
                "num_predict": 512,
            },
        }
        deadline = monotonic() + min(60, self.settings.llm_timeout_seconds)
        last_error: Exception | None = None
        for attempt in range(2):
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            try:
                async with asyncio.timeout(remaining):
                    async with httpx.AsyncClient(timeout=remaining) as client:
                        response = await client.post(
                            self.settings.llm_base_url.removesuffix("/v1").rstrip("/")
                            + "/api/chat",
                            json=payload,
                        )
                        response.raise_for_status()
                        body = response.json()
                if body.get("done_reason") == "length":
                    raise ValueError("Truncated response")
                self.last_usage = {
                    k: int(body[k])
                    for k in ("prompt_eval_count", "eval_count", "load_duration")
                    if k in body
                }
                result, self.rejected_fields = validate_extraction(
                    json.loads(body["message"]["content"]), message
                )
                return result
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as error:
                last_error = error
                if attempt == 0:
                    await asyncio.sleep(min(0.2, max(0, deadline - monotonic())))
            except (
                httpx.HTTPError,
                TimeoutError,
                ValueError,
                KeyError,
                TypeError,
                ValidationError,
            ) as error:
                last_error = error
                break
        raise ExtractorError("Grounded apparel extraction unavailable") from last_error
