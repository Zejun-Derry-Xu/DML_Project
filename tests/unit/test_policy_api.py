from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.v1 import policy
from app.db.session import get_db
from app.main import create_app


def test_policy_api_uses_saved_decision_and_checks_email(monkeypatch) -> None:
    session_id = uuid4()
    saved_case = SimpleNamespace(
        customer_email="customer@example.com",
        decision="ineligible",
        decision_reason="FINAL_SALE",
    )

    class FakeRepository:
        def __init__(self, db: object) -> None:
            pass

        def case_by_session(self, value: object) -> object:
            return saved_case if value == session_id else None

    app = create_app()
    app.dependency_overrides[get_db] = lambda: object()
    monkeypatch.setattr(policy, "ReturnRepository", FakeRepository)
    client = TestClient(app)
    payload = {
        "question": "Can I return this final sale item?",
        "session_id": str(session_id),
        "customer_email": "other@example.com",
    }
    assert client.post("/api/v1/policy/explain", json=payload).status_code == 403
    payload["customer_email"] = "customer@example.com"
    result = client.post("/api/v1/policy/explain", json=payload)
    assert result.status_code == 200
    assert result.json()["decision"] == "ineligible"
    assert result.json()["citations"][0]["clause_id"] == "RF-03"
