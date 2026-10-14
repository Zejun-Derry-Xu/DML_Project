from uuid import uuid4

from sqlalchemy import func, select

from app.db.models import ReturnRequestRecord


def test_two_eligible_sessions_cannot_confirm_same_item_twice(client, db_session):
    sessions = [str(uuid4()), str(uuid4())]
    questions = []
    for session in sessions:
        body = client.post(
            "/api/v1/returns/evaluate",
            json={
                "session_id": session,
                "customer_email": "june@example.com",
                "order_number": "ORD-1010",
                "reason": "does_not_fit",
                "used": False,
            },
        ).json()
        questions.append(body["question"]["question_id"])
    first = client.post(
        f"/api/v1/questions/{questions[0]}/answer",
        json={
            "session_id": sessions[0],
            "selected_value": "confirm",
        },
    )
    assert first.status_code == 200
    assert first.json()["state"] == "return_created"
    second = client.post(
        f"/api/v1/questions/{questions[1]}/answer",
        json={
            "session_id": sessions[1],
            "selected_value": "confirm",
        },
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ORDER_ALREADY_RETURNED"
    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(ReturnRequestRecord)) == 1
    third = client.post(
        "/api/v1/returns/evaluate",
        json={
            "customer_email": "june@example.com",
            "order_number": "ORD-1010",
        },
    )
    assert third.json()["reason_code"] == "ORDER_ALREADY_RETURNED"
