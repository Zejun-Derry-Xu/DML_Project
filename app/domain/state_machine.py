from datetime import UTC, datetime, timedelta
from typing import Literal

from app.domain.models import QuestionOption, QuestionRequest, ReturnCase
from app.domain.reason_codes import ReasonCode

QUESTION_TTL = timedelta(minutes=10)


def next_missing_field(
    case: ReturnCase, *, order_item_count: int | None = None
) -> Literal["order_id", "item_id", "reason", "used"] | None:
    if case.order_number is None:
        return "order_id"
    if order_item_count is not None and order_item_count > 1 and case.item_id is None:
        return "item_id"
    if case.reason is None:
        return "reason"
    if case.reason.value not in {"defective", "wrong_item"} and case.used is None:
        return "used"
    return None


def reason_for_missing(field: str) -> ReasonCode:
    return {
        "order_id": ReasonCode.MISSING_ORDER_ID,
        "item_id": ReasonCode.MISSING_ITEM_SELECTION,
        "reason": ReasonCode.MISSING_RETURN_REASON,
        "used": ReasonCode.MISSING_USAGE_STATUS,
    }[field]


def build_question(
    field: Literal["order_id", "item_id", "reason", "used", "opened", "confirm_return"],
    *,
    case_version: int,
    item_options: list[QuestionOption] | None = None,
    now: datetime | None = None,
) -> QuestionRequest:
    prompts = {
        "order_id": "What is your order number?",
        "item_id": "Which item would you like to return?",
        "reason": "Why would you like to return this item?",
        "used": "Has the item been used?",
        "opened": "Has the item been opened?",
        "confirm_return": "Would you like to submit the return request now?",
    }
    options: dict[str, list[QuestionOption]] = {
        "order_id": [],
        "item_id": item_options or [],
        "reason": [
            QuestionOption(value="defective", label="Defective or damaged"),
            QuestionOption(value="wrong_item", label="Wrong item received"),
            QuestionOption(value="changed_mind", label="No longer wanted"),
            QuestionOption(value="does_not_fit", label="Doesn't fit"),
            QuestionOption(value="other", label="Other"),
        ],
        "used": [
            QuestionOption(value="yes", label="Yes", description="The item has been used."),
            QuestionOption(value="no", label="No", description="The item has not been used."),
            QuestionOption(value="unknown", label="I'm not sure"),
        ],
        "opened": [
            QuestionOption(value="yes", label="Yes", description="The packaging has been opened."),
            QuestionOption(value="no", label="No", description="The item is still sealed."),
            QuestionOption(value="unknown", label="I'm not sure"),
        ],
        "confirm_return": [
            QuestionOption(value="confirm", label="Confirm return"),
            QuestionOption(value="cancel", label="Cancel"),
        ],
    }
    created_at = now or datetime.now(UTC)
    return QuestionRequest(
        field=field,
        prompt=prompts[field],
        options=options[field],
        allow_free_text=field != "confirm_return",
        expires_at=created_at + QUESTION_TTL,
        case_version=case_version,
    )
