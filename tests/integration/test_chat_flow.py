from uuid import uuid4


def test_natural_language_flow_asks_only_missing_questions(client):
    session_id = uuid4()
    response = client.post(
        "/api/v1/chat",
        json={
            "session_id": str(session_id),
            "customer_email": "june@example.com",
            "message": "I want to return ORD-1010 because the shirt doesn't fit.",
        },
    )
    assert response.status_code == 200
    assert response.json()["question"]["field"] == "used"

    response = client.post(
        "/api/v1/chat",
        json={
            "session_id": str(session_id),
            "customer_email": "june@example.com",
            "message": "No, I never used it.",
        },
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "eligible"
    assert response.json()["question"]["field"] == "confirm_return"

    response = client.post(
        "/api/v1/chat",
        json={
            "session_id": str(session_id),
            "customer_email": "june@example.com",
            "message": "Confirm return",
        },
    )
    assert response.status_code == 200
    assert response.json()["state"] == "return_created"


def test_conflicting_fact_escalates_to_human_review(client):
    session_id = uuid4()
    first = client.post(
        "/api/v1/chat",
        json={
            "session_id": str(session_id),
            "customer_email": "june@example.com",
            "message": "Return ORD-1010 because I changed my mind. I used it.",
        },
    )
    assert first.json()["reason_code"] == "USED_ITEM"

    second = client.post(
        "/api/v1/chat",
        json={
            "session_id": str(session_id),
            "customer_email": "june@example.com",
            "message": "Actually, I never used it.",
        },
    )
    assert second.json()["decision"] == "human_review"
    assert second.json()["reason_code"] == "INFORMATION_CONFLICT"


def test_item_name_selects_only_real_order_item(client):
    session_id = uuid4()
    first = client.post(
        "/api/v1/chat",
        json={
            "session_id": str(session_id),
            "customer_email": "june@example.com",
            "message": "I want to return ORD-1005.",
        },
    )
    assert first.json()["question"]["field"] == "item_id"

    second = client.post(
        "/api/v1/chat",
        json={
            "session_id": str(session_id),
            "customer_email": "june@example.com",
            "message": "The headphones",
        },
    )
    assert second.json()["question"]["field"] == "reason"
