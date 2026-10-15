"""Real API/SQLite conversation tests; no LLM stub can override policy decisions."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.db.models import OrderItemRecord, QuestionRequestRecord, ReturnCaseRecord

GOOD = {"stained": False, "damaged": False, "tags_attached": True, "tags_intact": True}


@pytest.fixture
def apparel(client, db_session):
    item = db_session.scalar(
        select(OrderItemRecord).where(OrderItemRecord.product_name == "Linen Shirt")
    )
    item.category = "apparel"
    db_session.commit()
    return client


SCENARIOS = [
    ({**GOOD, "used": True}, "eligible", "confirm_return"),
    ({**GOOD, "used": False}, "eligible", "confirm_return"),
    (GOOD, "eligible", "confirm_return"),
    ({"used": False}, "need_more_information", "stained"),
    ({"used": True}, "need_more_information", "stained"),
    ({"stained": False}, "need_more_information", "tags_attached"),
    ({"stained": False, "tags_attached": True}, "need_more_information", "tags_intact"),
    (
        {"stained": False, "tags_attached": True, "tags_intact": True},
        "need_more_information",
        "damaged",
    ),
    ({"stained": True}, "need_more_information", "condition_origin"),
    ({"tags_attached": False}, "need_more_information", "condition_origin"),
    ({"tags_intact": False}, "need_more_information", "condition_origin"),
    ({"damaged": True}, "need_more_information", "condition_origin"),
] + [
    ({field: value, "condition_origin": origin}, decision, None)
    for field, value in (
        ("stained", True),
        ("damaged", True),
        ("tags_attached", False),
        ("tags_intact", False),
    )
    for origin, decision in (
        ("customer", "ineligible"),
        ("pre_existing", "human_review"),
        ("unknown", "human_review"),
    )
]


@pytest.mark.parametrize("facts,decision,next_field", SCENARIOS)
def test_twenty_four_condition_conversations(apparel, facts, decision, next_field):
    session = str(uuid4())
    first = apparel.post(
        "/api/v1/returns/evaluate",
        json={
            "session_id": session,
            "order_number": "ORD-1010",
            "customer_email": "june@example.com",
        },
    ).json()
    assert first["question"]["field"] == "reason"
    payload = {"session_id": session, "reason": "does_not_fit", **facts}
    response = apparel.post("/api/v1/returns/evaluate", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == decision
    assert body["return_request"] is None
    assert body["policy_version"] == "mvp-2.0.0"
    assert body["policy_evidence"]
    if next_field:
        assert body["question"]["field"] == next_field
    else:
        assert body["question"] is None
    resumed = apparel.get(f"/api/v1/return-cases/{session}").json()
    assert resumed["decision"] == decision
    if decision == "eligible":
        confirmed = apparel.post(
            f"/api/v1/questions/{body['question']['question_id']}/answer",
            json={
                "session_id": session,
                "selected_value": "confirm",
            },
        ).json()
        assert confirmed["state"] == "return_created"
        assert (
            apparel.get(f"/api/v1/return-cases/{session}").json()["return_request"]["id"]
            == confirmed["return_request"]["id"]
        )


def test_real_chat_buttons_and_duplicate_protection(apparel):
    session = str(uuid4())
    body = apparel.post(
        "/api/v1/chat",
        json={
            "session_id": session,
            "customer_email": "june@example.com",
            "message": "Return ORD-1010 because the shirt doesn't fit. I used it.",
        },
    ).json()
    assert body["question"]["field"] == "stained"
    for field, answer in (
        ("stained", "no"),
        ("tags_attached", "yes"),
        ("tags_intact", "yes"),
        ("damaged", "no"),
        ("confirm_return", "confirm"),
    ):
        assert body["question"]["field"] == field
        body = apparel.post(
            f"/api/v1/questions/{body['question']['question_id']}/answer",
            json={
                "session_id": session,
                "selected_value": answer,
            },
        ).json()
    assert body["state"] == "return_created"
    duplicate = apparel.post(
        "/api/v1/returns/evaluate",
        json={
            "order_number": "ORD-1010",
            "customer_email": "june@example.com",
            "reason": "does_not_fit",
            **GOOD,
        },
    ).json()
    assert duplicate["reason_code"] == "ORDER_ALREADY_RETURNED"


def test_changed_apparel_answer_escalates(apparel):
    session = str(uuid4())
    apparel.post(
        "/api/v1/returns/evaluate",
        json={
            "session_id": session,
            "order_number": "ORD-1010",
            "customer_email": "june@example.com",
            "reason": "does_not_fit",
            "stained": False,
        },
    )
    changed = apparel.post(
        "/api/v1/returns/evaluate", json={"session_id": session, "stained": True}
    ).json()
    assert changed["reason_code"] == "INFORMATION_CONFLICT"
    assert changed["return_request"] is None


def test_old_confirmation_invalidated_but_completed_version_preserved(apparel, db_session):
    session = str(uuid4())
    body = apparel.post(
        "/api/v1/returns/evaluate",
        json={
            "session_id": session,
            "order_number": "ORD-1010",
            "customer_email": "june@example.com",
            "reason": "does_not_fit",
            **GOOD,
        },
    ).json()
    case = db_session.scalar(
        select(ReturnCaseRecord).where(ReturnCaseRecord.session_id == UUID(session))
    )
    case.policy_version = "mvp-1.0.0"
    case.stained = case.tags_attached = case.tags_intact = case.damaged = None
    db_session.commit()
    stale = apparel.post(
        f"/api/v1/questions/{body['question']['question_id']}/answer",
        json={
            "session_id": session,
            "selected_value": "confirm",
        },
    )
    assert stale.status_code == 409
    resumed = apparel.get(f"/api/v1/return-cases/{session}").json()
    assert resumed["question"]["field"] == "stained"
    assert resumed["return_request"] is None
    assert (
        db_session.get(QuestionRequestRecord, UUID(body["question"]["question_id"])).status
        == "replaced"
    )
    case.status = "closed"
    case.policy_version = "mvp-1.0.0"
    case.decision = "ineligible"
    case.decision_reason = "USED_ITEM"
    db_session.commit()
    historical = apparel.get(f"/api/v1/return-cases/{session}").json()
    assert historical["policy_version"] == "mvp-1.0.0"
    assert historical["policy_evidence"][0]["clause_id"] == "P-USAGE"


def test_condition_unknown_origin_goes_to_person(apparel):
    session = str(uuid4())
    body = apparel.post(
        "/api/v1/returns/evaluate",
        json={
            "session_id": session,
            "order_number": "ORD-1010",
            "customer_email": "june@example.com",
            "reason": "does_not_fit",
            "tags_attached": False,
        },
    ).json()
    body = apparel.post(
        f"/api/v1/questions/{body['question']['question_id']}/answer",
        json={
            "session_id": session,
            "selected_value": "unknown",
        },
    ).json()
    assert body["reason_code"] == "CONDITION_REQUIRES_REVIEW"
