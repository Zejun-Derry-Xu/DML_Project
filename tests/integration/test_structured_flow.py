from uuid import uuid4


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
