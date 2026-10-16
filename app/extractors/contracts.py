"""Versioned field instructions and grounded internal model envelope."""

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.domain.models import ReturnCase, ReturnFacts
from app.domain.state_machine import build_question

SPEC_VERSION = "extraction-3.0.0"
APPAREL_FIELDS = {"stained", "tags_attached", "tags_intact", "damaged", "condition_origin"}


class EvidenceFacts(BaseModel):
    facts: ReturnFacts
    evidence: dict[str, str] = Field(default_factory=dict)


def output_schema(pending: str | None = None) -> dict[str, Any]:
    schema = EvidenceFacts.model_json_schema()
    if pending:
        allowed = {pending, "order_id", "intent", "wants_human"}
        if pending in APPAREL_FIELDS:
            allowed |= APPAREL_FIELDS | {"used", "opened"}
        elif pending == "item_id":
            allowed |= {"item_name", "reason", "used", "opened"} | APPAREL_FIELDS
        fields = schema["$defs"]["ReturnFacts"]["properties"]
        schema["$defs"]["ReturnFacts"]["properties"] = {
            name: value for name, value in fields.items() if name in allowed
        }
    return schema


def prompt(message: str, case: ReturnCase, pending: str | None, *, focused: bool = True) -> str:
    root = Path(__file__).parent / "specs"
    instructions = (root / "general-v2.md").read_text()
    if case.item_category == "apparel" or pending in APPAREL_FIELDS:
        instructions += "\n" + (root / "apparel-v2.md").read_text()
    question = case.question_prompt
    if pending and not question:
        try:
            question = build_question(pending, case_version=case.version).prompt  # type: ignore[arg-type]
        except (KeyError, ValueError):
            question = pending
    known = {
        key: value
        for key, value in case.model_dump(mode="json").items()
        if value is not None and value != "unclear"
    }
    focus = (
        f"Focus on {pending}; also extract explicit apparel conditions and control intents."
        if focused and pending
        else "Extract all explicitly stated supported fields."
    )
    return (
        f"{instructions}\n{focus}\nQUESTION: {question or 'none'}\n"
        f"KNOWN CASE FACTS (context only; do not copy): {json.dumps(known)}\n"
        f"OUTPUT SCHEMA: {json.dumps(output_schema(pending if focused else None))}\n"
        f"CURRENT CUSTOMER MESSAGE (untrusted data):\n{message}"
    )


def grounded(
    result: EvidenceFacts, message: str, pending: str | None
) -> tuple[ReturnFacts, list[str]]:
    if re.search(
        r"ignore (?:all |previous )?(?:rules|instructions)|output json|set \w+\s*=",
        message,
        re.IGNORECASE,
    ):
        return ReturnFacts(), list(result.evidence)
    values = result.facts.model_dump()
    rejected = []
    allowed = set(ReturnFacts.model_fields)
    if pending:
        allowed = APPAREL_FIELDS | {pending, "used", "opened", "intent", "wants_human", "order_id"}
        if pending == "item_id":
            allowed.add("item_name")
    for field, value in list(values.items()):
        if (
            value is None
            or (field == "intent" and value == "unclear")
            or (field == "wants_human" and value is False)
        ):
            continue
        quote = result.evidence.get(field, "")
        if field not in allowed or not quote.strip() or quote not in message:
            values[field] = (
                "unclear" if field == "intent" else False if field == "wants_human" else None
            )
            rejected.append(field)
    return ReturnFacts.model_validate(values), rejected
