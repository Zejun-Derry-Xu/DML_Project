from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.models import OrderItem, OrderSnapshot, ReturnDecision, ReturnReason
from app.domain.policy_engine import evaluate_return
from app.domain.reason_codes import ReasonCode

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def make_order(*, status: str = "delivered", delivered_days_ago: int | None = 5) -> OrderSnapshot:
    item = OrderItem(id=uuid4(), product_name="Test Item", price=Decimal("20.00"))
    return OrderSnapshot(
        id=uuid4(),
        order_number="ORD-TEST",
        customer_email="test@example.com",
        status=status,
        ordered_at=NOW - timedelta(days=10),
        delivered_at=None
        if delivered_days_ago is None
        else NOW - timedelta(days=delivered_days_ago),
        items=[item],
    )


@pytest.mark.parametrize(
    ("mutate", "reason", "used", "expected_decision", "expected_code"),
    [
        (
            lambda order, item: setattr(order, "status", "shipped"),
            ReturnReason.CHANGED_MIND,
            False,
            ReturnDecision.INELIGIBLE,
            ReasonCode.ORDER_NOT_DELIVERED,
        ),
        (
            lambda order, item: setattr(order, "delivered_at", NOW - timedelta(days=31)),
            ReturnReason.CHANGED_MIND,
            False,
            ReturnDecision.INELIGIBLE,
            ReasonCode.OUTSIDE_RETURN_WINDOW,
        ),
        (
            lambda order, item: setattr(item, "final_sale", True),
            ReturnReason.CHANGED_MIND,
            False,
            ReturnDecision.INELIGIBLE,
            ReasonCode.FINAL_SALE,
        ),
        (
            lambda order, item: setattr(item, "return_status", "requested"),
            ReturnReason.CHANGED_MIND,
            False,
            ReturnDecision.INELIGIBLE,
            ReasonCode.ORDER_ALREADY_RETURNED,
        ),
        (
            lambda order, item: None,
            None,
            None,
            ReturnDecision.NEED_MORE_INFORMATION,
            ReasonCode.MISSING_RETURN_REASON,
        ),
        (
            lambda order, item: None,
            ReturnReason.CHANGED_MIND,
            None,
            ReturnDecision.NEED_MORE_INFORMATION,
            ReasonCode.MISSING_USAGE_STATUS,
        ),
        (
            lambda order, item: None,
            ReturnReason.DEFECTIVE,
            None,
            ReturnDecision.HUMAN_REVIEW,
            ReasonCode.DEFECT_REQUIRES_REVIEW,
        ),
        (
            lambda order, item: None,
            ReturnReason.CHANGED_MIND,
            True,
            ReturnDecision.INELIGIBLE,
            ReasonCode.USED_ITEM,
        ),
        (
            lambda order, item: None,
            ReturnReason.CHANGED_MIND,
            False,
            ReturnDecision.ELIGIBLE,
            ReasonCode.ELIGIBLE,
        ),
    ],
)
def test_policy_outcomes(mutate, reason, used, expected_decision, expected_code):
    order = make_order()
    item = order.items[0]
    mutate(order, item)

    result = evaluate_return(order, item, reason=reason, used=used, now=NOW)

    assert result.decision == expected_decision
    assert result.reason_code == expected_code


def test_exactly_thirty_days_is_inside_window():
    order = make_order(delivered_days_ago=30)
    result = evaluate_return(
        order,
        order.items[0],
        reason=ReturnReason.CHANGED_MIND,
        used=False,
        now=NOW,
    )
    assert result.decision == ReturnDecision.ELIGIBLE
