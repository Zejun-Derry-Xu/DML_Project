def test_policy_endpoint_returns_versioned_citation(client) -> None:
    response = client.post("/api/v1/policy/ask", json={"question": "What is the return deadline?"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["policy_version"] == "mvp-1.0.0"
    assert body["citations"][0]["clause_id"] == "P-WINDOW"


def test_policy_endpoint_does_not_decide_a_specific_order(client) -> None:
    response = client.post("/api/v1/policy/ask", json={"question": "Can I return ORD-1010?"})
    assert response.status_code == 200
    assert response.json()["status"] == "case_specific_not_supported"
    assert response.json()["citations"] == []


def test_policy_endpoint_abstains_when_no_clause_matches(client) -> None:
    response = client.post("/api/v1/policy/ask", json={"question": "What is tomorrow's weather?"})
    assert response.status_code == 200
    assert response.json()["status"] == "no_match"


def test_policy_help_does_not_answer_or_replace_pending_return_question(client) -> None:
    from uuid import uuid4

    session = str(uuid4())
    first = client.post(
        "/api/v1/chat",
        json={
            "session_id": session,
            "customer_email": "june@example.com",
            "message": "Return ORD-1010 because the shirt doesn't fit.",
        },
    ).json()
    assert first["question"]["field"] == "used"
    result = client.post(
        "/api/v1/policy/ask",
        json={
            "question": "What is the return deadline?",
            "scope": "eligibility",
        },
    ).json()
    assert result["citations"][0]["clause_id"] == "P-WINDOW"
    resumed = client.get(f"/api/v1/return-cases/{session}").json()
    assert resumed["question"]["question_id"] == first["question"]["question_id"]
    assert resumed["return_request"] is None
