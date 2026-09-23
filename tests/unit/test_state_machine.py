from datetime import UTC, datetime
from uuid import uuid4

from app.domain.models import QuestionOption, ReturnCase, ReturnReason
from app.domain.state_machine import build_question, next_missing_field


def test_missing_fields_are_requested_in_priority_order():
    case = ReturnCase(session_id=uuid4())
    assert next_missing_field(case) == "order_id"
    case.order_number = "ORD-1005"
    assert next_missing_field(case, order_item_count=2) == "item_id"
    case.item_id = uuid4()
    assert next_missing_field(case, order_item_count=2) == "reason"
    case.reason = ReturnReason.CHANGED_MIND
    assert next_missing_field(case, order_item_count=2) == "used"
    case.used = False
    assert next_missing_field(case, order_item_count=2) is None


def test_defect_does_not_ask_usage_status():
    case = ReturnCase(
        session_id=uuid4(),
        order_number="ORD-1006",
        item_id=uuid4(),
        reason=ReturnReason.DEFECTIVE,
    )
    assert next_missing_field(case, order_item_count=1) is None


def test_item_options_are_not_invented():
    options = [QuestionOption(value="item-1", label="Headphones")]
    question = build_question(
        "item_id",
        case_version=3,
        item_options=options,
        now=datetime(2026, 9, 23, tzinfo=UTC),
    )
    assert question.options == options
    assert question.case_version == 3
    assert question.allow_free_text is True


def test_confirmation_only_offers_confirm_or_cancel():
    question = build_question("confirm_return", case_version=1)
    assert [option.value for option in question.options] == ["confirm", "cancel"]
    assert question.allow_free_text is False
