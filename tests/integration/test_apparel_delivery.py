"""New product flow through HTTP. The semantic fake is not a Qwen quality score."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import (
    CustomerRecord,
    QuestionRequestRecord,
    ReturnCaseRecord,
    SupportTicketRecord,
)
from app.extractors.apparel_llm import Extraction, LLMFactExtractor, Observation
from scripts.seed_data import stable_id
from scripts.seed_demo_accounts import seed_demo

GOOD = {"stained": False, "damaged": False, "tags_attached": True, "tags_intact": True}


@pytest.fixture
def demo(client, db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "workflow_mode", "apparel")
    monkeypatch.setattr(settings, "demo_enabled", True)
    monkeypatch.setattr(settings, "demo_session_secret", "x" * 64)
    monkeypatch.setattr(settings, "extraction_mode", "guided")
    seed_demo(db_session)
    db_session.commit()
    result = client.post(
        "/api/v1/demo/session", json={"customer_id": str(stable_id("demo-customer", "alice"))}
    )
    assert result.status_code == 200
    return client


def chat(client, session, text="I'd like a clothing return"):
    response = client.post("/api/v1/chat", json={"session_id": session, "message": text})
    assert response.status_code == 200, response.text
    return response.json()


def answer(client, result, value):
    response = client.post(
        f"/api/v1/questions/{result['question']['question_id']}/answer",
        json={
            "session_id": result["session_id"],
            "selected_value": value,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def start(client, order="DEMO-1001"):
    result = chat(client, str(uuid4()))
    assert result["question"]["field"] == "order_id"
    return answer(client, result, order)


def complete_cards(client, result, overrides=None):
    values = {
        "reason_text": "too small",
        **{k: "yes" if v else "no" for k, v in GOOD.items()},
        "condition_origin": "customer",
        **(overrides or {}),
    }
    for _ in range(10):
        question = result.get("question")
        if not question or question["field"] == "confirm_return":
            break
        if question["field"] == "reason_text":
            result = chat(client, result["session_id"], values["reason_text"])
        else:
            result = answer(client, result, values[question["field"]])
    return result


def test_demo_is_allowlisted_and_cookies_are_signed(demo, db_session):
    names = demo.get("/api/v1/demo/customers").json()
    assert len(names) == 2
    assert all("email" not in row for row in names)
    real = db_session.scalar(
        select(CustomerRecord).where(CustomerRecord.email == "june@example.com")
    )
    assert demo.post("/api/v1/demo/session", json={"customer_id": str(real.id)}).status_code == 404
    demo.cookies.set("returnflow_demo", "forged")
    assert demo.get("/api/v1/orders").status_code == 401


@pytest.mark.parametrize("bad_id", [False, True])
def test_experimental_harness_adapter_through_api_keeps_missing_state_safe(
    demo, monkeypatch, bad_id
):
    import json

    import httpx

    from app.extractors.apparel_harness import HarnessExtractor
    from app.services import apparel_service

    result = start(demo)
    result = chat(demo, result["session_id"], "too small")
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "extraction_mode", "llm")
    monkeypatch.setattr(get_settings(), "llm_provider", "ollama")
    monkeypatch.setattr(
        apparel_service, "LLMFactExtractor", lambda s: HarnessExtractor(s, "span_ids")
    )
    original = httpx.AsyncClient

    def respond(request):
        payload = json.loads(request.content)
        assert "source_spans" in json.loads(payload["messages"][1]["content"])
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": json.dumps(
                        {
                            "intent": "unclear",
                            "intent_evidence_ids": [],
                            "facts": [
                                {
                                    "field": "stained",
                                    "value": None,
                                    "state": "uncertain",
                                    "evidence_ids": ["S99" if bad_id else "S1"],
                                }
                            ],
                        }
                    )
                },
                "done_reason": "stop",
            },
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw)
    )
    result = chat(demo, result["session_id"], "I am not sure.")
    assert result["return_request"] is None
    assert result["decision"] != "eligible"
    assert result["degraded"] is bad_id
    assert result["facts"]["stained"].get("value") is None
    assert result["facts"]["stained"]["state"] in {"missing", "unknown"}


def test_owned_orders_and_case_answers_are_isolated(demo):
    orders = demo.get("/api/v1/orders").json()
    assert all(o["order_number"].startswith("DEMO-1") for o in orders)
    assert demo.get("/api/v1/orders/DEMO-2001?email=demo-bob@example.invalid").status_code == 404
    result = start(demo)
    demo.post("/api/v1/demo/session", json={"customer_id": str(stable_id("demo-customer", "bob"))})
    assert demo.get(f"/api/v1/return-cases/{result['session_id']}").status_code == 404
    assert (
        demo.post(
            f"/api/v1/questions/{result['question']['question_id']}/answer",
            json={
                "session_id": result["session_id"],
                "selected_value": "unknown",
            },
        ).status_code
        == 404
    )
    assert (
        demo.post(
            "/api/v1/chat",
            json={
                "session_id": result["session_id"],
                "message": "hello",
            },
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "order,code",
    [
        ("DEMO-1002", "OUTSIDE_RETURN_WINDOW"),
        ("DEMO-1003", "FINAL_SALE"),
        ("DEMO-1005", "ORDER_NOT_DELIVERED"),
        ("DEMO-1004", "NON_APPAREL"),
    ],
)
def test_hard_checks_before_model(demo, monkeypatch, order, code):
    async def forbidden(*args):
        pytest.fail("No model on rejected or unsupported orders")

    monkeypatch.setattr(LLMFactExtractor, "extract", forbidden)
    result = start(demo, order)
    assert result["reason_code"] == code
    assert result["question"] is None
    assert bool(result["support_ticket"]) == (code == "NON_APPAREL")


def test_guided_flow_confirmation_and_duplicate_guard(demo):
    result = complete_cards(demo, start(demo))
    assert result["question"]["field"] == "confirm_return"
    assert result["degraded"] is True
    assert result["facts"]["reason_text"] == "too small"
    confirmation = result
    created = answer(demo, result, "confirm")
    assert created["state"] == "return_created"
    assert answer(demo, confirmation, "confirm")["return_request"] == created["return_request"]
    assert start(demo)["reason_code"] == "ORDER_ALREADY_RETURNED"


def test_unknown_collects_other_fields_then_one_ticket(demo, db_session):
    result = start(demo)
    result = chat(demo, result["session_id"], "It doesn't fit")
    result = answer(demo, result, "unknown")
    assert result["question"]["field"] == "damaged"
    assert not result["support_ticket"]
    completed = complete_cards(demo, result)
    assert completed["state"] == "escalated"
    assert completed["support_ticket"]["id"]
    assert not completed["return_request"]
    assert (
        demo.get(f"/api/v1/return-cases/{completed['session_id']}").json()["support_ticket"]
        == completed["support_ticket"]
    )
    assert (
        chat(demo, completed["session_id"], "again")["support_ticket"]
        == completed["support_ticket"]
    )
    assert db_session.scalar(select(func.count()).select_from(SupportTicketRecord)) == 1


@pytest.mark.parametrize(
    "origin,expected",
    [("customer", "ineligible"), ("pre_existing", "human_review"), ("unknown", "human_review")],
)
def test_adverse_origin_routes_after_collection(demo, origin, expected):
    result = complete_cards(demo, start(demo), {"stained": "yes", "condition_origin": origin})
    assert result["decision"] == expected
    assert result["question"] is None


def test_unknown_text_not_repeated_forever(demo):
    result = start(demo)
    for text in ("too small", "hmm", "hmm"):
        result = chat(demo, result["session_id"], text)
    assert result["question"]["field"] == "damaged"


def test_real_evidence_candidate_flow_and_conflict_after_eligible(demo, monkeypatch):
    async def fake(self, message, context):
        values = (
            {"reason_text": "too small", **GOOD}
            if message == "too small"
            else {"stained": True}
            if message.startswith("Actually")
            else {}
        )
        return Extraction(
            intent="unclear",
            intent_evidence="",
            facts=[
                Observation(field=k, value=v, evidence=message, state="stated")
                for k, v in values.items()
            ],
        )

    monkeypatch.setattr(LLMFactExtractor, "extract", fake)
    result = start(demo)
    result = chat(demo, result["session_id"], "too small")
    assert result["question"]["field"] == "confirm_return"
    result = chat(demo, result["session_id"], "Actually it is stained")
    assert result["question"]["field"] == "stained"
    assert result["question"]["prompt"].startswith("Your statements differ")
    assert not result["return_request"]


def test_legacy_readonly_and_stale_expired_cards(demo, db_session):
    legacy = ReturnCaseRecord(
        session_id=uuid4(),
        customer_email="demo-alice@example.invalid",
        workflow_version="legacy",
        policy_version="mvp-1.0.0",
    )
    db_session.add(legacy)
    db_session.commit()
    result = demo.get(f"/api/v1/return-cases/{legacy.session_id}").json()
    assert result["read_only"] is True
    assert chat(demo, str(legacy.session_id), "change")["read_only"] is True
    assert legacy.policy_version == "mvp-1.0.0"
    result = start(demo)
    old = result["question"]["question_id"]
    question = db_session.get(QuestionRequestRecord, UUID(old))
    question.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()
    assert (
        demo.post(
            f"/api/v1/questions/{old}/answer",
            json={
                "session_id": result["session_id"],
                "selected_value": "unknown",
            },
        ).status_code
        == 410
    )
    restored = demo.get(f"/api/v1/return-cases/{result['session_id']}").json()
    assert restored["question"]["question_id"] != old


def test_no_structured_bypass_and_no_store(demo):
    assert demo.post("/api/v1/returns/evaluate", json={"reason": "changed_mind"}).status_code == 409
    result = demo.get("/api/v1/orders")
    assert result.headers["cache-control"] == "no-store"


def test_immediate_human_and_cancel(demo):
    result = chat(demo, str(uuid4()), "talk to a human")
    assert result["support_ticket"]
    assert not result["question"]
    result = chat(demo, str(uuid4()), "cancel")
    assert result["state"] == "cancelled"
