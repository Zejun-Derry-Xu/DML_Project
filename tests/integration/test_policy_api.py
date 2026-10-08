def test_policy_endpoint_returns_versioned_citation(client) -> None:
    response = client.post(
        "/api/v1/policy/ask", json={"question": "What is the return deadline?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["policy_version"] == "mvp-1.0.0"
    assert body["citations"][0]["clause_id"] == "P-WINDOW"


def test_policy_endpoint_does_not_decide_a_specific_order(client) -> None:
    response = client.post(
        "/api/v1/policy/ask", json={"question": "Can I return ORD-1010?"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "case_specific_not_supported"
    assert response.json()["citations"] == []


def test_policy_endpoint_abstains_when_no_clause_matches(client) -> None:
    response = client.post(
        "/api/v1/policy/ask", json={"question": "What is tomorrow's weather?"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "no_match"
