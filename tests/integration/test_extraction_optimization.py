"""Additional multi-turn boundary scenarios through actual HTTP handlers/SQLite."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.db.models import OrderItemRecord, OrderRecord, ReturnCaseRecord

GOOD = {"stained": False, "damaged": False, "tags_attached": True, "tags_intact": True}


@pytest.fixture
def clothing(client, db_session):
    item = db_session.scalar(
        select(OrderItemRecord).where(OrderItemRecord.product_name == "Linen Shirt")
    )
    item.category = "apparel"
    db_session.commit()
    return client


@pytest.mark.parametrize(
    "pending,message,decision,next_field",
    [
        (
            "tags_attached",
            "This shirt no longer has its tags attached.",
            "need_more_information",
            "condition_origin",
        ),
        (
            "tags_attached",
            "If the tags are attached, can I return it?",
            "need_more_information",
            "tags_attached",
        ),
        (
            "tags_attached",
            "The tags are attached to a different shirt, not this one.",
            "need_more_information",
            "tags_attached",
        ),
        ("stained", "I cannot tell whether it is stained.", "human_review", None),
        (
            "tags_intact",
            "I need to inspect it before I can answer that question.",
            "human_review",
            None,
        ),
        ("damaged", "There is no damage to this shirt.", "eligible", "confirm_return"),
        (
            "tags_intact",
            "The tags on this shirt are damaged.",
            "need_more_information",
            "condition_origin",
        ),
        ("stained", "It arrived stained.", "human_review", None),
    ],
)
def test_condition_boundaries(clothing, db_session, pending, message, decision, next_field):
    session = str(uuid4())
    initial = clothing.post(
        "/api/v1/returns/evaluate",
        json={
            "session_id": session,
            "order_number": "ORD-1010",
            "customer_email": "june@example.com",
            "reason": "does_not_fit",
            **{f: v for f, v in GOOD.items() if f != pending},
        },
    ).json()
    assert initial["question"]["field"] == pending
    response = clothing.post("/api/v1/chat", json={"session_id": session, "message": message})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == decision
    assert body["return_request"] is None
    assert (body["question"]["field"] if body["question"] else None) == next_field
    if pending == "tags_intact" and "damaged" in message:
        case = db_session.scalar(
            select(ReturnCaseRecord).where(ReturnCaseRecord.session_id == UUID(session))
        )
        assert case.damaged is False


@pytest.mark.parametrize(
    "message",
    [
        "My phone number is 1234567890.",
        "It cost $1234.50.",
        "The date is 2026-10-15.",
        "Order 1234567890 or order 9876543210; I cannot tell.",
    ],
)
def test_non_order_and_ambiguous_identifiers(clothing, message):
    session = str(uuid4())
    first = clothing.post(
        "/api/v1/chat",
        json={
            "session_id": session,
            "customer_email": "june@example.com",
            "message": "I want to return a shirt.",
        },
    ).json()
    assert first["question"]["field"] == "order_id"
    body = clothing.post("/api/v1/chat", json={"session_id": session, "message": message}).json()
    assert body["question"]["field"] == "order_id"
    assert body["return_request"] is None


@pytest.mark.parametrize("bare", [True, False])
def test_native_numeric_order_is_not_rewritten(clothing, db_session, bare):
    record = db_session.scalar(select(OrderRecord).where(OrderRecord.order_number == "ORD-1010"))
    record.order_number = "001234567890"
    db_session.commit()
    session = str(uuid4())
    clothing.post(
        "/api/v1/chat",
        json={
            "session_id": session,
            "customer_email": "june@example.com",
            "message": "I want to return the shirt.",
        },
    )
    body = clothing.post(
        "/api/v1/chat",
        json={
            "session_id": session,
            "message": "001234567890" if bare else "My order number is 001234567890.",
        },
    ).json()
    assert body["question"]["field"] == "reason"
    resumed = clothing.get(f"/api/v1/return-cases/{session}").json()
    assert resumed["question"]["field"] == "reason"
    case = db_session.scalar(
        select(ReturnCaseRecord).where(ReturnCaseRecord.session_id == UUID(session))
    )
    assert case.order_number == "001234567890"


def test_same_message_conflict_does_not_approve(clothing):
    session = str(uuid4())
    clothing.post(
        "/api/v1/returns/evaluate",
        json={
            "session_id": session,
            "order_number": "ORD-1010",
            "customer_email": "june@example.com",
            "reason": "does_not_fit",
            "stained": False,
            "damaged": False,
            "tags_intact": True,
        },
    )
    body = clothing.post(
        "/api/v1/chat",
        json={
            "session_id": session,
            "message": "The tags are attached; the tags are not attached.",
        },
    ).json()
    assert body["return_request"] is None
    assert body["decision"] != "eligible"
    assert body["question"]["field"] == "tags_attached"


def test_human_request_during_condition_question(clothing):
    session = str(uuid4())
    clothing.post(
        "/api/v1/chat",
        json={
            "session_id": session,
            "customer_email": "june@example.com",
            "message": "Return ORD-1010 because the shirt doesn't fit.",
        },
    )
    body = clothing.post(
        "/api/v1/chat", json={"session_id": session, "message": "I would like a human agent."}
    ).json()
    assert body["decision"] == "human_review"
    assert body["return_request"] is None


def test_conflict_retains_other_same_item_facts_without_approval(clothing, db_session):
    session = str(uuid4())
    clothing.post(
        "/api/v1/returns/evaluate",
        json={
            "session_id": session,
            "order_number": "ORD-1010",
            "customer_email": "june@example.com",
            "reason": "does_not_fit",
        },
    )
    body = clothing.post(
        "/api/v1/chat",
        json={
            "session_id": session,
            "message": "The tags are attached; the tags are not attached; the shirt has no stains.",
        },
    ).json()
    assert body["question"]["field"] == "tags_attached"
    assert body["decision"] == "need_more_information"
    assert body["return_request"] is None
    case = db_session.scalar(
        select(ReturnCaseRecord).where(ReturnCaseRecord.session_id == UUID(session))
    )
    assert case.stained is False
    assert case.tags_attached is None
