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


def validate_extraction(
    body: Any, message: str, *, diagnostics: list[dict[str, str]] | None = None
) -> tuple[Extraction, list[str]]:
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
            if diagnostics is not None:
                if not fact.evidence.strip() or fact.evidence not in message:
                    reason = "evidence_not_exact_current_message"
                elif fact.state != "stated" and fact.value is not None:
                    reason = "nonstated_requires_null"
                elif fact.field in BOOLEAN_FIELDS and type(fact.value) is not bool:
                    reason = "boolean_type"
                elif fact.field == "condition_origin":
                    reason = "origin_enum"
                elif (
                    fact.field == "order_number"
                    and isinstance(fact.value, str)
                    and not re.fullmatch(r"[A-Za-z0-9-]{1,50}", fact.value)
                ):
                    reason = "order_identifier_shape"
                else:
                    reason = "text_value_not_verbatim_in_evidence"
                diagnostics.append({"field": fact.field, "reason": reason})
    if result.intent != "unclear" and (
        not result.intent_evidence or result.intent_evidence not in message
    ):
        result.intent = "unclear"
    return result.model_copy(update={"facts": accepted}), rejected


class LLMFactExtractor:
    def __init__(self, settings: Settings, *, capture_diagnostics: bool = False) -> None:
        self.settings = settings
        self.capture_diagnostics = capture_diagnostics
        self.last_usage: dict[str, int] = {}
        self.rejected_fields: list[str] = []
        self.last_trace: dict[str, Any] = {}
        self.max_attempts = 2

    def build_payload(self, message: str, context: dict[str, Any]) -> dict[str, Any]:
        instructions = (Path(__file__).parent / "specs/apparel-llm-v1.md").read_text()
        return {
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

    def decode_response(self, content: str, message: str) -> Extraction:
        self.last_trace["stage"] = "response_json"
        parsed = json.loads(content)
        if self.capture_diagnostics:
            self.last_trace["parsed_candidates"] = parsed
        reasons: list[dict[str, str]] = []
        self.last_trace["stage"] = "schema_and_evidence"
        result, self.rejected_fields = validate_extraction(parsed, message, diagnostics=reasons)
        self.last_trace["rejections"] = reasons
        return result

    async def extract(self, message: str, context: dict[str, Any]) -> Extraction:
        self.last_usage = {}
        self.rejected_fields = []
        self.last_trace = {}
        if self.settings.extraction_mode == "guided":
            raise ExtractorError("Guided mode: natural-language semantics are unavailable")
        if self.settings.llm_provider != "ollama":
            raise ExtractorError("Apparel LLM mode requires the configured Ollama provider")
        payload = self.build_payload(message, context)
        if self.capture_diagnostics:
            self.last_trace["request"] = payload
        deadline = monotonic() + min(60, self.settings.llm_timeout_seconds)
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            try:
                self.last_trace["stage"] = "transport"
                self.last_trace["transport_attempts"] = attempt + 1
                async with asyncio.timeout(remaining):
                    async with httpx.AsyncClient(timeout=remaining) as client:
                        response = await client.post(
                            self.settings.llm_base_url.removesuffix("/v1").rstrip("/")
                            + "/api/chat",
                            json=payload,
                        )
                        response.raise_for_status()
                        body = response.json()
                if self.capture_diagnostics:
                    self.last_trace["raw_content"] = body.get("message", {}).get("content")
                    self.last_trace["done_reason"] = body.get("done_reason")
                self.last_usage = {
                    k: int(body[k])
                    for k in ("prompt_eval_count", "eval_count", "load_duration")
                    if k in body
                }
                if body.get("done_reason") == "length":
                    self.last_trace["stage"] = "truncated"
                    raise ValueError("Truncated response")
                result = self.decode_response(body["message"]["content"], message)
                if self.capture_diagnostics:
                    self.last_trace["accepted"] = result.model_dump(mode="json")
                self.last_trace["stage"] = "complete"
                return result
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as error:
                last_error = error
                if attempt + 1 < self.max_attempts:
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
        self.last_trace["error"] = type(last_error).__name__ if last_error else "deadline"
        if isinstance(last_error, ValidationError):
            self.last_trace["schema_errors"] = [
                {"location": list(e["loc"]), "type": e["type"]}
                for e in last_error.errors(include_input=False)
            ]
        elif isinstance(last_error, ValueError) and str(last_error).startswith("wire_"):
            self.last_trace["contract_error"] = str(last_error)
        raise ExtractorError("Grounded apparel extraction unavailable") from last_error
