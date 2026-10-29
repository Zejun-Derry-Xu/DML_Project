"""LLM-first semantics with mechanical evidence checks, not keyword reclassification."""

import asyncio
import json
import re
from pathlib import Path
from time import monotonic
from typing import Any, Literal, NoReturn

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import Settings
from app.extractors.base import ExtractorError
from app.extractors.dashscope import (
    build_payload as build_dashscope_payload,
)
from app.extractors.dashscope import (
    chat_completions_url,
    completion_text,
    initial_response_format,
    usage_counts,
)

VERSION = "apparel-extraction-2.1.0"
# Nginx proxy_read_timeout is 70s. Stay inside that so one extraction can finish.
EXTRACTION_BUDGET_SECONDS = 60
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


class ChecklistReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["none", "all_clear", "uncertain", "exception"] = "none"
    evidence: str = ""
    submit_requested: bool = False
    submit_evidence: str = ""
    policy_question: str = ""
    topics: list[Literal["condition", "tags", "origin", "window", "tag_cleanliness"]] = Field(
        default_factory=list, max_length=5
    )


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal["return", "cancel", "human", "other", "unclear"]
    intent_evidence: str
    facts: list[Observation] = Field(max_length=12)
    checklist_reply: ChecklistReply = Field(default_factory=ChecklistReply)


def generation_schema() -> dict[str, Any]:
    """Bind field/state/value at generation time; retain the historical internal DTO.

    Provider grammar is not a semantic authority. The existing exact-evidence and
    duplicate/type checks still run after generation, including for older payloads.
    """
    schema = Extraction.model_json_schema()

    def branch(fields: list[str], value: dict[str, Any], states: list[str]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "field": {"type": "string", "enum": fields},
                "value": value,
                "state": {"type": "string", "enum": states},
                "evidence": {"type": "string", "minLength": 1},
            },
            "required": ["field", "value", "state", "evidence"],
        }

    schema["properties"]["facts"] = {
        "type": "array",
        "maxItems": 12,
        "items": {
            "anyOf": [
                branch(sorted(BOOLEAN_FIELDS), {"type": "boolean"}, ["stated"]),
                branch(
                    ["condition_origin"],
                    {
                        "type": "string",
                        "enum": ["customer", "pre_existing"],
                    },
                    ["stated"],
                ),
                branch(
                    ["reason_text", "order_number", "item_name"],
                    {
                        "type": "string",
                        "minLength": 1,
                    },
                    ["stated"],
                ),
                branch(sorted(FIELDS), {"type": "null"}, ["uncertain", "conflict"]),
            ]
        },
    }
    # Observation's permissive union remains an internal/backward-compatible DTO,
    # but is not advertised as the model's field-independent generation contract.
    schema.get("$defs", {}).pop("Observation", None)
    return schema


def validate_extraction(
    body: Any, message: str, *, diagnostics: list[dict[str, str]] | None = None
) -> tuple[Extraction, list[str]]:
    result = Extraction.model_validate(body, strict=True)
    reply = result.checklist_reply
    if message.strip().casefold().rstrip(".!?。！？") in {
        "yes",
        "okay",
        "ok",
        "sure",
        "嗯",
        "可以",
        "好",
        "好的",
        "行",
    }:
        reply.kind, reply.submit_requested = "none", False
    if reply.kind != "none" and (not reply.evidence.strip() or reply.evidence not in message):
        reply.kind = "none"
    if reply.submit_requested and (
        not reply.submit_evidence.strip() or reply.submit_evidence not in message
    ):
        reply.submit_requested = False
    if not reply.policy_question.strip() or reply.policy_question not in message:
        reply.policy_question = ""
        if reply.kind != "exception":
            reply.topics = []
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
        spec = (
            "apparel-checklist-v2.md"
            if self.settings.collection_style == "checklist"
            else "apparel-llm-v1.md"
        )
        instructions = (Path(__file__).parent / "specs" / spec).read_text()
        schema = generation_schema()
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
                            "schema": schema,
                        }
                    ),
                },
            ],
            "format": schema,
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
        if self.settings.llm_provider == "ollama":
            return await self._extract_ollama(message, context)
        if self.settings.llm_provider == "dashscope":
            return await self._extract_dashscope(message, context)
        raise ExtractorError(
            "Apparel LLM mode requires the configured Ollama or DashScope provider"
        )

    def _budget(self) -> float:
        return monotonic() + min(EXTRACTION_BUDGET_SECONDS, self.settings.llm_timeout_seconds)

    def _fail(self, last_error: Exception | None) -> NoReturn:
        self.last_trace["error"] = type(last_error).__name__ if last_error else "deadline"
        if isinstance(last_error, ValidationError):
            self.last_trace["schema_errors"] = [
                {"location": list(error["loc"]), "type": error["type"]}
                for error in last_error.errors(include_input=False)
            ]
        elif isinstance(last_error, ValueError) and str(last_error).startswith("wire_"):
            self.last_trace["contract_error"] = str(last_error)
        raise ExtractorError("Grounded apparel extraction unavailable") from last_error

    async def _extract_ollama(self, message: str, context: dict[str, Any]) -> Extraction:
        payload = self.build_payload(message, context)
        if self.capture_diagnostics:
            self.last_trace["request"] = payload
        deadline = self._budget()
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
        self._fail(last_error)

    async def _extract_dashscope(self, message: str, context: dict[str, Any]) -> Extraction:
        if not self.settings.dashscope_api_key.strip():
            self.last_trace["stage"] = "auth"
            self._fail(ExtractorError("missing_api_key"))
        schema = generation_schema()
        fmt = initial_response_format(self.settings.dashscope_response_format)
        instructions = (
            Path(__file__).parent
            / "specs"
            / (
                "apparel-checklist-v2.md"
                if self.settings.collection_style == "checklist"
                else "apparel-llm-v1.md"
            )
        ).read_text()
        deadline = self._budget()
        headers = {
            "Authorization": f"Bearer {self.settings.dashscope_api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            payload = build_dashscope_payload(
                self.settings, instructions, message, context, schema, fmt
            )
            if self.capture_diagnostics:
                self.last_trace["request"] = payload
            try:
                self.last_trace["stage"] = "transport"
                self.last_trace["transport_attempts"] = attempt + 1
                self.last_trace["response_format"] = fmt
                async with asyncio.timeout(remaining):
                    async with httpx.AsyncClient(timeout=remaining) as client:
                        response = await client.post(
                            chat_completions_url(self.settings),
                            json=payload,
                            headers=headers,
                        )
                        if (
                            response.status_code == 400
                            and self.settings.dashscope_response_format == "auto"
                            and fmt == "json_schema"
                        ):
                            # Singapore documents json_schema as not supported yet.
                            fmt = "json_object"
                            self.last_trace["structured_output"] = "json_object_fallback"
                            self.last_trace["response_format"] = fmt
                            payload = build_dashscope_payload(
                                self.settings, instructions, message, context, schema, fmt
                            )
                            if self.capture_diagnostics:
                                self.last_trace["request"] = payload
                            response = await client.post(
                                chat_completions_url(self.settings),
                                json=payload,
                                headers=headers,
                            )
                        if response.status_code == 429 or response.status_code >= 500:
                            raise _RetryableStatus(response.status_code)
                        response.raise_for_status()
                        body = response.json()
                self.last_usage = usage_counts(body)
                result = self.decode_response(completion_text(body), message)
                if self.capture_diagnostics:
                    self.last_trace["accepted"] = result.model_dump(mode="json")
                self.last_trace["stage"] = "complete"
                return result
            except (
                _RetryableStatus,
                httpx.ConnectError,
                httpx.ReadError,
                httpx.RemoteProtocolError,
            ) as error:
                last_error = error
                if attempt + 1 < self.max_attempts:
                    await asyncio.sleep(min(0.2, max(0, deadline - monotonic())))
            except (
                httpx.HTTPError,
                TimeoutError,
                ValueError,
                KeyError,
                IndexError,
                TypeError,
                ValidationError,
            ) as error:
                last_error = error
                break
        self._fail(last_error)


class _RetryableStatus(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"retryable HTTP {status_code}")
