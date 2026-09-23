from datetime import UTC, datetime, timedelta

from app.domain.models import (
    OrderItem,
    OrderSnapshot,
    PolicyResult,
    ReturnDecision,
    ReturnReason,
)
from app.domain.reason_codes import ReasonCode

RETURN_WINDOW = timedelta(days=30)


def evaluate_return(
    order: OrderSnapshot,
    item: OrderItem,
    *,
    reason: ReturnReason | None,
    used: bool | None,
    damaged: bool | None = None,
    wants_human: bool = False,
    now: datetime | None = None,
) -> PolicyResult:
    """Evaluate the four MVP policies in a deterministic, short-circuiting order."""
    current_time = now or datetime.now(UTC)

    if wants_human:
        return PolicyResult(
            decision=ReturnDecision.HUMAN_REVIEW,
            reason_code=ReasonCode.USER_REQUESTED_HUMAN,
        )
    if order.status != "delivered" or order.delivered_at is None:
        return PolicyResult(
            decision=ReturnDecision.INELIGIBLE,
            reason_code=ReasonCode.ORDER_NOT_DELIVERED,
        )
    delivered_at = order.delivered_at
    if delivered_at.tzinfo is None:
        delivered_at = delivered_at.replace(tzinfo=UTC)
    if current_time - delivered_at > RETURN_WINDOW:
        return PolicyResult(
            decision=ReturnDecision.INELIGIBLE,
            reason_code=ReasonCode.OUTSIDE_RETURN_WINDOW,
        )
    if item.final_sale:
        return PolicyResult(
            decision=ReturnDecision.INELIGIBLE,
            reason_code=ReasonCode.FINAL_SALE,
        )
    if item.return_status:
        return PolicyResult(
            decision=ReturnDecision.INELIGIBLE,
            reason_code=ReasonCode.ORDER_ALREADY_RETURNED,
        )
    if reason is None:
        return PolicyResult(
            decision=ReturnDecision.NEED_MORE_INFORMATION,
            reason_code=ReasonCode.MISSING_RETURN_REASON,
        )
    if reason in {ReturnReason.DEFECTIVE, ReturnReason.WRONG_ITEM} or damaged is True:
        return PolicyResult(
            decision=ReturnDecision.HUMAN_REVIEW,
            reason_code=ReasonCode.DEFECT_REQUIRES_REVIEW,
        )
    if used is None:
        return PolicyResult(
            decision=ReturnDecision.NEED_MORE_INFORMATION,
            reason_code=ReasonCode.MISSING_USAGE_STATUS,
        )
    if used:
        return PolicyResult(
            decision=ReturnDecision.INELIGIBLE,
            reason_code=ReasonCode.USED_ITEM,
        )
    return PolicyResult(
        decision=ReturnDecision.ELIGIBLE,
        reason_code=ReasonCode.ELIGIBLE,
    )
