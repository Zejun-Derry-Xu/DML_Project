"""Configuration and evidence tests, not model-quality scores."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.models import OrderItem, OrderSnapshot
from app.extractors.apparel_llm import validate_extraction
from app.policy.apparel import load_apparel_policy, precheck


def test_policy_configuration_changes_deadline_and_its_text_together():
    policy = load_apparel_policy()
    changed = policy.model_validate({**policy.model_dump(), "return_window_days": 45})
    item = OrderItem(id=uuid4(), product_name="Shirt", category="apparel", price=Decimal("1"))
    now = datetime.now(UTC)
    order = OrderSnapshot(
        id=uuid4(),
        order_number="00001",
        customer_email="x@example.invalid",
        status="delivered",
        ordered_at=now - timedelta(days=60),
        delivered_at=now - timedelta(days=40),
        items=[item],
    )
    assert precheck(order, item, policy, now) == "OUTSIDE_RETURN_WINDOW"
    assert precheck(order, item, changed, now) is None
    assert "45 days" in changed.corpus().by_id("A-WINDOW").content
    assert load_apparel_policy().return_window_days == 30
    order.delivered_at = now - timedelta(days=30)
    assert precheck(order, item, policy, now) is None


@pytest.mark.parametrize(
    "field,value,evidence,accepted",
    [
        ("stained", False, "no stains", True),
        ("tags_attached", False, "no longer attached", True),
        ("stained", False, "invented evidence", False),
        ("reason_text", "too small", "too small", True),
        ("reason_text", "does_not_fit", "too small", False),
        ("order_number", "000001", "order 000001", True),
        ("damaged", "false", "no damage", False),
    ],
)
def test_structural_evidence_validation(field, value, evidence, accepted):
    message = "no stains; no longer attached; too small; order 000001; no damage"
    result, rejected = validate_extraction(
        {
            "intent": "unclear",
            "intent_evidence": "",
            "facts": [{"field": field, "value": value, "state": "stated", "evidence": evidence}],
        },
        message,
    )
    assert bool(result.facts) == accepted
    assert bool(rejected) != accepted


def test_unknown_is_not_false_and_duplicate_fields_rejected():
    body = {
        "intent": "unclear",
        "intent_evidence": "",
        "facts": [
            {"field": "stained", "value": None, "state": "uncertain", "evidence": "not sure"}
        ],
    }
    result, _ = validate_extraction(body, "not sure")
    assert result.facts[0].value is None
    body["facts"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        validate_extraction(body, "not sure")
