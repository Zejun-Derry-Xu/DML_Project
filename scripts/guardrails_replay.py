"""Observed-dialogue replay helpers. Never use annotations as conversation history."""

from typing import Any

from app.domain.models import ReturnCase, ReturnFacts

HISTORY_FIELDS = {
    "order_number",
    "item_name",
    "reason",
    "used",
    "opened",
    "damaged",
    "stained",
    "tags_attached",
    "tags_intact",
    "condition_origin",
}


def merge_prediction(state: dict[str, Any], facts: ReturnFacts, conflicts: list[str]):
    result = dict(state)
    cross_turn_conflicts = []
    for field, value in facts.model_dump(mode="json").items():
        target = "order_number" if field == "order_id" else field
        if target not in HISTORY_FIELDS or value is None or field in conflicts:
            continue
        previous = result.get(target)
        if previous is not None and previous != value:
            cross_turn_conflicts.append(field)
        else:
            result[target] = value
    return result, cross_turn_conflicts


def case_for_turn(session_id, state: dict[str, Any], row):
    # current_case from a projection can contain prior gold. Deliberately ignore it.
    return ReturnCase(
        session_id=session_id,
        **state,
        question_prompt=row.get("question_prompt") or None,
        pending_question=row.get("pending_question"),
    )
