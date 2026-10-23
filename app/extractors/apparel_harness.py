"""Opt-in offline harness variants. No keyword inference or model repair calls."""

import json
import re
from pathlib import Path
from typing import Any, Literal

from app.config import Settings
from app.extractors.apparel_llm import (
    BOOLEAN_FIELDS,
    FIELDS,
    Extraction,
    LLMFactExtractor,
    validate_extraction,
)

VERSION = "apparel-harness-1.0.0"
Protocol = Literal["typed", "span_ids"]


def source_spans(message: str) -> list[dict[str, Any]]:
    """Lossless mechanical sentence boundaries; never strip negation or guess scope."""
    ends = [m.end() for m in re.finditer(r"[.!?;](?=\s|$)|\n", message)]
    ends = sorted(set([*ends, len(message)]))
    intervals = []
    start = 0
    for end in ends:
        if end > start:
            intervals.append((start, end))
            start = end
    if not intervals:
        intervals = [(0, len(message))]
    # Bound ID count, not source coverage. Consecutive pieces may be grouped.
    group_size = max(1, (len(intervals) + 15) // 16)
    grouped = [
        (intervals[i][0], intervals[min(i + group_size, len(intervals)) - 1][1])
        for i in range(0, len(intervals), group_size)
    ]
    return [
        {"id": f"S{i + 1}", "start": start, "end": end, "text": message[start:end]}
        for i, (start, end) in enumerate(grouped)
    ]


def output_schema(protocol: Protocol, spans: list[dict[str, Any]]) -> dict[str, Any]:
    evidence_key = "evidence_ids" if protocol == "span_ids" else "evidence"
    evidence_schema: dict[str, Any] = (
        {
            "type": "array",
            "items": {"type": "string", "enum": [s["id"] for s in spans]},
            "maxItems": 4,
        }
        if protocol == "span_ids"
        else {"type": "string"}
    )

    def fact(fields: list[str], value: dict[str, Any], states: list[str]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "field": {"type": "string", "enum": fields},
                "value": value,
                "state": {"type": "string", "enum": states},
                evidence_key: evidence_schema,
            },
            "required": ["field", "value", "state", evidence_key],
        }

    intent_key = "intent_evidence_ids" if protocol == "span_ids" else "intent_evidence"
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "intent": {"type": "string", "enum": ["return", "cancel", "human", "other", "unclear"]},
            intent_key: evidence_schema,
            "facts": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "anyOf": [
                        fact(sorted(BOOLEAN_FIELDS), {"type": "boolean"}, ["stated"]),
                        fact(
                            ["condition_origin"],
                            {"type": "string", "enum": ["customer", "pre_existing", "unknown"]},
                            ["stated"],
                        ),
                        fact(
                            ["item_name", "order_number", "reason_text"],
                            {"type": "string"},
                            ["stated"],
                        ),
                        fact(
                            sorted(FIELDS),
                            {"type": "null"},
                            ["uncertain", "not_mentioned", "conflict"],
                        ),
                    ]
                },
            },
        },
        "required": ["intent", intent_key, "facts"],
    }


def check_wire(body: Any, protocol: Protocol, spans: list[dict[str, Any]]) -> None:
    """Local counterpart of the generation contract; provider constraints aren't trusted."""
    evidence_key = "evidence_ids" if protocol == "span_ids" else "evidence"
    intent_key = "intent_evidence_ids" if protocol == "span_ids" else "intent_evidence"
    if not isinstance(body, dict) or set(body) != {"intent", intent_key, "facts"}:
        raise ValueError("wire_top_level")
    if body["intent"] not in {"return", "cancel", "human", "other", "unclear"}:
        raise ValueError("wire_intent")
    if not isinstance(body["facts"], list) or len(body["facts"]) > 12:
        raise ValueError("wire_fact_list")
    seen = set()
    allowed_ids = {s["id"] for s in spans}

    def evidence_ok(value: Any) -> bool:
        if protocol == "typed":
            return isinstance(value, str)
        return (
            isinstance(value, list)
            and len(value) <= 4
            and all(isinstance(v, str) and v in allowed_ids for v in value)
            and len(value) == len(set(value))
        )

    if not evidence_ok(body[intent_key]):
        raise ValueError("wire_intent_evidence")
    for f in body["facts"]:
        if not isinstance(f, dict) or set(f) != {"field", "value", "state", evidence_key}:
            raise ValueError("wire_fact_shape")
        field, value, state = f["field"], f["value"], f["state"]
        if not isinstance(field, str) or field not in FIELDS or field in seen:
            raise ValueError("wire_field_or_duplicate")
        seen.add(field)
        if state not in {"stated", "uncertain", "not_mentioned", "conflict"}:
            raise ValueError("wire_state")
        if not evidence_ok(f[evidence_key]):
            raise ValueError("wire_evidence")
        if state != "stated":
            valid = value is None
        elif field in BOOLEAN_FIELDS:
            valid = type(value) is bool
        elif field == "condition_origin":
            valid = isinstance(value, str) and value in {"customer", "pre_existing", "unknown"}
        else:
            valid = isinstance(value, str)
        if not valid:
            raise ValueError("wire_value_state_type")


class HarnessExtractor(LLMFactExtractor):
    def __init__(
        self, settings: Settings, protocol: Protocol, *, capture_diagnostics: bool = False
    ) -> None:
        super().__init__(settings, capture_diagnostics=capture_diagnostics)
        self.protocol = protocol
        self.max_attempts = 1

    def build_payload(self, message: str, context: dict[str, Any]) -> dict[str, Any]:
        payload = super().build_payload(message, context)
        spans = source_spans(message)
        schema = output_schema(self.protocol, spans)
        instructions = (Path(__file__).parent / "specs/apparel-harness-v1.md").read_text()
        instructions += (
            "\nEvidence: select evidence_ids from the supplied source_spans; do not copy quotes. "
            "Use intent_evidence_ids for intent. Empty IDs are valid only for absence/unclear."
            if self.protocol == "span_ids"
            else "\nEvidence: copy an exact substring from the current message into evidence. "
            "Use intent_evidence for intent."
        )
        compact_context = {
            k: context[k]
            for k in ("question", "target", "selected_item", "known_facts_reference_only")
            if k in context
        }
        user: dict[str, Any] = {
            "context_only": compact_context,
            "current_customer_message_untrusted": message,
            "schema": schema,
        }
        if self.protocol == "span_ids":
            user["source_spans"] = [{"id": s["id"], "text": s["text"]} for s in spans]
        payload["messages"] = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps(user)},
        ]
        payload["format"] = schema
        return payload

    def decode_response(self, content: str, message: str) -> Extraction:
        self.last_trace["stage"] = "response_json"
        parsed = json.loads(content)
        if self.capture_diagnostics:
            self.last_trace["parsed_candidates"] = parsed
        spans = source_spans(message)
        self.last_trace["stage"] = "wire_contract"
        check_wire(parsed, self.protocol, spans)
        if self.protocol == "span_ids":
            by_id = {s["id"]: s for s in spans}

            def recover(ids: list[str]) -> str:
                if not ids:
                    return ""
                selected = [by_id[i] for i in ids]
                # Minimal contiguous cover preserves intervening negation/context.
                return message[min(s["start"] for s in selected) : max(s["end"] for s in selected)]

            body = {
                "intent": parsed["intent"],
                "intent_evidence": recover(parsed["intent_evidence_ids"]),
                "facts": [
                    {
                        "field": f["field"],
                        "value": f["value"],
                        "state": f["state"],
                        "evidence": recover(f["evidence_ids"]),
                    }
                    for f in parsed["facts"]
                ],
            }
            if self.capture_diagnostics:
                self.last_trace["source_spans"] = spans
                self.last_trace["resolved_candidates"] = body
        else:
            body = parsed
        reasons: list[dict[str, str]] = []
        self.last_trace["stage"] = "schema_and_evidence"
        result, self.rejected_fields = validate_extraction(body, message, diagnostics=reasons)
        self.last_trace["rejections"] = reasons
        return result
