from uuid import uuid4

import pytest

from app.domain.models import ReturnCase
from app.extractors.compact import prompt, schema, validate
from app.extractors.scoped import order_identifier, scoped_conditions


def case():
    return ReturnCase(session_id=uuid4(), item_category="apparel", item_name="shirt", used=False)


def test_compact_schema_requires_target_and_keeps_control_fields():
    fields = schema("tags_intact", True)["properties"]["facts"]
    assert set(fields["required"]) == {
        "stained",
        "damaged",
        "tags_attached",
        "tags_intact",
        "condition_origin",
    }
    assert {"order_id", "intent", "wants_human", "stained", "damaged"} <= set(fields["properties"])
    text = prompt("No.", case(), "tags_intact")
    assert '"used": false' in text
    assert "session_id" not in text and "customer_email" not in text


@pytest.mark.parametrize(
    "text,pending,field,value,quote",
    [
        (
            "If the tags are attached, can I return it?",
            "tags_attached",
            "tags_attached",
            True,
            "the tags are attached",
        ),
        (
            "I cannot tell whether the tags are intact.",
            "tags_intact",
            "tags_intact",
            True,
            "the tags are intact",
        ),
        (
            "The tags are attached to another item, not this one.",
            "tags_attached",
            "tags_attached",
            True,
            "The tags are attached",
        ),
        ("The tags are attached.", "tags_intact", "tags_intact", True, "The tags are attached"),
        ("The tags are damaged.", "damaged", "damaged", True, "The tags are damaged"),
        (
            "The tags were removed.",
            "condition_origin",
            "condition_origin",
            "customer",
            "The tags were removed",
        ),
        ("My phone number is 1234567890.", "order_id", "order_id", "1234567890", "1234567890"),
    ],
)
def test_quote_presence_does_not_establish_entailment(text, pending, field, value, quote):
    facts, diagnostics, _ = validate(
        {"answer_state": "stated", "facts": {field: {"value": value, "evidence": "E0"}}},
        text,
        case(),
        pending,
    )
    assert getattr(facts, field) is None
    assert field in diagnostics["rejected_fields"]


def test_missing_evidence_is_not_repaired():
    facts, diagnostics, trace = validate(
        {
            "answer_state": "stated",
            "facts": {"damaged": {"value": False, "evidence": "E999"}},
        },
        "No damage",
        case(),
        "damaged",
    )
    assert facts.damaged is None
    assert diagnostics["rejection_causes"]["damaged"] == "unknown_evidence_id"
    assert trace["model_candidates"]["damaged"] is False


def test_native_order_context_and_ambiguity():
    assert order_identifier("My order is 001234567890.")[0] == "001234567890"
    assert order_identifier("001234567890", "order_id")[0] == "001234567890"
    assert order_identifier("001234567890")[0] is None
    assert order_identifier("Order 123456 or order 987654")[1]


@pytest.mark.parametrize(
    "text",
    [
        "If I damaged it, would that matter?",
        "I probably caused the damage.",
        "It arrived undamaged.",
        "It arrived without stains or damage.",
        "It was not my fault.",
        "Did I cause the problems?",
    ],
)
def test_origin_requires_asserted_adverse_provenance(text):
    assert (
        scoped_conditions(text, case(), "condition_origin").values.get("condition_origin") is None
    )


def test_origin_conflict_is_not_overwritten_by_uncertainty():
    result = scoped_conditions("I caused the damage; I don't know who caused it.", case(), None)
    assert result.values.get("condition_origin") is None
    assert "condition_origin" in result.conflicts


@pytest.mark.parametrize(
    "text",
    [
        "The order ID of the item I want to return is 001234567890.",
        "001234567890 is my order ID.",
    ],
)
def test_explicit_native_order_label_in_natural_word_order(text):
    assert order_identifier(text)[0] == "001234567890"
