from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.db.models import QuestionRequestRecord, ReturnCaseRecord


def answer(client, response, session_id, value):
    question_id = response.json()["question"]["question_id"]
    return client.post(
        f"/api/v1/questions/{question_id}/answer",
        json={"session_id": str(session_id), "selected_value": value},
    )


def test_complete_structured_return_flow(client):
    session_id = uuid4()
    response = client.post(
        "/api/v1/returns/evaluate",
        json={
            "session_id": str(session_id),
            "customer_email": "june@example.com",
            "order_number": "ORD-1010",
        },
    )
    assert response.status_code == 200
    assert response.json()["question"]["field"] == "reason"

    response = answer(client, response, session_id, "does_not_fit")
    assert response.json()["question"]["field"] == "used"

    response = answer(client, response, session_id, "no")
    assert response.json()["decision"] == "eligible"
    assert response.json()["question"]["field"] == "confirm_return"

    confirm_id = response.json()["question"]["question_id"]
    response = answer(client, response, session_id, "confirm")
    assert response.json()["state"] == "return_created"
    assert response.json()["return_request"]["rma_number"].startswith("RMA-")

    duplicate = client.post(
        f"/api/v1/questions/{confirm_id}/answer",
        json={"session_id": str(session_id), "selected_value": "confirm"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "QUESTION_ALREADY_RESOLVED"

    resumed = client.get(f"/api/v1/return-cases/{session_id}")
    assert resumed.json()["state"] == "return_created"
    assert resumed.json()["question"] is None
    assert resumed.json()["return_request"]["rma_number"].startswith("RMA-")


def test_final_sale_short_circuits_questions(client):
    response = client.post(
        "/api/v1/returns/evaluate",
        json={
            "customer_email": "june@example.com",
            "order_number": "ORD-1004",
        },
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "ineligible"
    assert response.json()["reason_code"] == "FINAL_SALE"
    assert response.json()["question"] is None


def test_multiple_items_use_server_generated_options(client):
    response = client.post(
        "/api/v1/returns/evaluate",
        json={
            "customer_email": "june@example.com",
            "order_number": "ORD-1005",
        },
    )
    body = response.json()
    assert body["question"]["field"] == "item_id"
    assert {option["label"] for option in body["question"]["options"]} == {
        "Headphones",
        "Cable",
    }


def test_identity_mismatch_is_rejected(client):
    response = client.get("/api/v1/orders/ORD-1010?email=mallory@example.com")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "IDENTITY_MISMATCH"


def test_pending_question_survives_resume(client):
    session_id = uuid4()
    first = client.post(
        "/api/v1/returns/evaluate",
        json={
            "session_id": str(session_id),
            "customer_email": "june@example.com",
            "order_number": "ORD-1010",
        },
    )
    resumed = client.get(f"/api/v1/return-cases/{session_id}")
    assert resumed.status_code == 200
    assert resumed.json()["question"]["question_id"] == first.json()["question"]["question_id"]


def test_expired_answer_is_rejected(client, db_session):
    session_id = uuid4()
    first = client.post(
        "/api/v1/returns/evaluate",
        json={
            "session_id": str(session_id),
            "customer_email": "june@example.com",
            "order_number": "ORD-1010",
        },
    )
    question_id = first.json()["question"]["question_id"]
    question = db_session.get(QuestionRequestRecord, UUID(question_id))
    question.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    response = client.post(
        f"/api/v1/questions/{question_id}/answer",
        json={"session_id": str(session_id), "selected_value": "changed_mind"},
    )
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "QUESTION_EXPIRED"


def test_cross_session_and_stale_answers_are_rejected(client, db_session):
    session_id = uuid4()
    first = client.post(
        "/api/v1/returns/evaluate",
        json={
            "session_id": str(session_id),
            "customer_email": "june@example.com",
            "order_number": "ORD-1010",
        },
    )
    question_id = first.json()["question"]["question_id"]
    mismatch = client.post(
        f"/api/v1/questions/{question_id}/answer",
        json={"session_id": str(uuid4()), "selected_value": "changed_mind"},
    )
    assert mismatch.status_code == 403

    case = db_session.query(ReturnCaseRecord).filter_by(session_id=session_id).one()
    case.version += 1
    db_session.commit()
    stale = client.post(
        f"/api/v1/questions/{question_id}/answer",
        json={"session_id": str(session_id), "selected_value": "changed_mind"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_ANSWER"
