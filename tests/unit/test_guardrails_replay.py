from uuid import uuid4

from app.domain.models import ReturnFacts
from scripts.guardrails_replay import case_for_turn, merge_prediction


def test_replay_does_not_read_gold_history_or_current_answer():
    row = {
        "current_case": {"order_number": "GOLD-HIDDEN"},
        "expected": {"order_id": "GOLD-ANSWER"},
        "question_prompt": "What is your order number?",
        "pending_question": "order_id",
    }
    case = case_for_turn(uuid4(), {}, row)
    assert case.order_number is None
    assert case.question_prompt == row["question_prompt"]
    predicted, _ = merge_prediction({}, ReturnFacts(order_id="001234", used=False), [])
    next_case = case_for_turn(uuid4(), predicted, row)
    assert next_case.order_number == "001234"
    assert next_case.used is False


def test_replay_restores_only_predictions_and_retains_conflicts():
    previous = {"order_number": "001234", "tags_attached": True}
    actual = ReturnFacts(order_id="005678", tags_attached=False, damaged=False)
    merged, conflicts = merge_prediction(previous, actual, ["tags_attached"])
    assert merged == {"order_number": "001234", "tags_attached": True, "damaged": False}
    assert conflicts == ["order_id"]
