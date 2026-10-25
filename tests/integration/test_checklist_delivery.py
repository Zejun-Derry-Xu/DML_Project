"""HTTP protocol with mocked Ollama transport, not real Qwen quality/latency."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import QuestionRequestRecord, ReturnCaseRecord, ReturnRequestRecord
from app.extractors.apparel_llm import Extraction
from tests.integration.test_apparel_delivery import answer, start
from tests.integration.test_apparel_delivery import demo as historical_demo  # noqa: F401


@pytest.fixture
def checklist(request, monkeypatch):
    client = request.getfixturevalue("historical_demo")
    settings = get_settings()
    monkeypatch.setattr(settings, "collection_style", "checklist")
    monkeypatch.setattr(settings, "extraction_mode", "llm")
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    script, calls = {}, []
    original = httpx.AsyncClient

    def respond(request):
        payload = json.loads(request.content)
        data = json.loads(payload["messages"][1]["content"])
        message = data["current_customer_message_untrusted"]
        calls.append(data)
        result = script.get(
            message, Extraction(intent="unclear", intent_evidence="", facts=[]).model_dump()
        )
        if callable(result):
            result = result()
        return httpx.Response(
            200, json={"message": {"content": json.dumps(result)}, "done_reason": "stop"}
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(respond), **kw)
    )
    return client, script, calls


def interpretation(message, *, kind="none", submit=False, facts=None, question="", topics=None):
    return {
        "intent": "unclear",
        "intent_evidence": "",
        "facts": facts or [],
        "checklist_reply": {
            "kind": kind,
            "evidence": message if kind != "none" else "",
            "submit_requested": submit,
            "submit_evidence": message if submit else "",
            "policy_question": question,
            "topics": topics or [],
        },
    }


def fact(field, value, evidence, state="stated"):
    return {"field": field, "value": value, "state": state, "evidence": evidence}


def send(client, previous, text, *, bind=True):
    payload = {"session_id": previous["session_id"], "message": text}
    if bind and previous.get("question"):
        payload["in_reply_to_question_id"] = previous["question"]["question_id"]
    response = client.post("/api/v1/chat", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_all_clear_and_submit_is_one_atomic_application_without_reason(checklist, db_session):
    client, script, calls = checklist
    current = start(client)
    assert current["question"]["field"] == "condition_checklist"
    assert len(current["question"]["checklist_items"]) == 4
    text = "上述问题都没有，并提交退货。"
    script[text] = interpretation(
        text,
        kind="all_clear",
        submit=True,
        facts=[
            fact("stained", False, text),
            fact("damaged", False, text),
            fact("tags_attached", True, text),
            fact("tags_intact", True, text),
        ],
    )
    calls.clear()
    result = send(client, current, text)
    assert result["state"] == "return_created" and result["return_request"]
    assert result["facts"]["reason_text"] is None
    assert len(calls) == 1
    assert all(
        result["facts"][f]["source"] == "user_attestation"
        for f in ("stained", "damaged", "tags_attached", "tags_intact")
    )
    again = send(client, current, text)
    assert again["return_request"] == result["return_request"]
    assert db_session.scalar(select(func.count()).select_from(ReturnRequestRecord)) == 1
    case = db_session.scalar(
        select(ReturnCaseRecord).where(ReturnCaseRecord.session_id == UUID(current["session_id"]))
    )
    assert (
        case.field_observations["_attestations"][0]["snapshot"]["question_id"]
        == current["question"]["question_id"]
    )


def test_all_clear_without_action_requires_only_submission_confirmation(checklist):
    client, script, _ = checklist
    text = "All of these conditions are met."
    script[text] = interpretation(text, kind="all_clear")
    result = send(client, start(client), text)
    assert result["question"]["field"] == "confirm_return"
    assert not result["return_request"]
    assert answer(client, result, "confirm")["state"] == "return_created"


def test_unbound_collective_claim_never_submits(checklist):
    client, script, _ = checklist
    text = "None apply; submit my return."
    script[text] = interpretation(text, kind="all_clear", submit=True)
    result = send(client, start(client), text, bind=False)
    assert result["question"]["field"] == "condition_checklist"
    assert not result["return_request"]
    assert not any(
        isinstance(v, dict) and v.get("source") == "user_attestation"
        for v in result["facts"].values()
    )


@pytest.mark.parametrize("expired", [False, True])
def test_wrong_or_expired_question_rejected_before_model(checklist, db_session, expired):
    client, _, calls = checklist
    current = start(client)
    qid = current["question"]["question_id"]
    if expired:
        db_session.get(QuestionRequestRecord, UUID(qid)).expires_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
        db_session.commit()
    calls.clear()
    result = client.post(
        "/api/v1/chat",
        json={
            "session_id": current["session_id"],
            "message": "All clear and submit",
            "in_reply_to_question_id": qid if expired else str(uuid4()),
        },
    )
    assert result.status_code == (410 if expired else 409)
    assert not calls


def test_model_off_button_attests_all_and_retries_idempotently(checklist, monkeypatch):
    client, _, calls = checklist
    monkeypatch.setattr(get_settings(), "extraction_mode", "guided")
    current = start(client)
    assert current["degraded"]
    calls.clear()
    result = answer(client, current, "attest_and_submit")
    assert result["state"] == "return_created"
    assert (
        answer(client, current, "attest_and_submit")["return_request"] == result["return_request"]
    )
    assert not calls


def test_exception_beats_collective_and_origin_is_asked_before_unrelated_fields(checklist):
    client, script, _ = checklist
    text = "All fine, but the tags were cut. Can I return it?"
    script[text] = interpretation(
        text,
        kind="all_clear",
        submit=True,
        facts=[fact("tags_attached", False, "tags were cut")],
        question="Can I return it?",
        topics=["tags", "origin"],
    )
    result = send(client, start(client), text)
    assert not result["return_request"]
    assert result["question"]["field"] == "condition_origin"
    assert {"A-CONDITION", "A-ORIGIN"} <= {c["clause_id"] for c in result["policy_evidence"]}
    assert answer(client, result, "customer")["decision"] == "ineligible"


@pytest.mark.parametrize("origin", ["pre_existing", "unknown"])
def test_delivery_and_unknown_origins_go_to_review_without_other_condition_questions(
    checklist, origin
):
    client, script, _ = checklist
    text = "The tags are removed."
    script[text] = interpretation(
        text, kind="exception", facts=[fact("tags_attached", False, text)]
    )
    result = send(client, start(client), text)
    result = answer(client, result, origin)
    assert result["state"] == "escalated" and not result["question"]


def test_clean_is_not_everything_clear_and_policy_questions_preserve_progress(
    checklist, db_session
):
    client, script, _ = checklist
    text = "The shirt is clean."
    script[text] = interpretation(text, facts=[fact("stained", False, text)])
    current = send(client, start(client), text)
    assert current["question"]["field"] == "condition_checklist"
    assert "tags_intact" not in current["facts"]
    query = "What if tags are cut?"
    script[query] = interpretation(query, question=query, topics=["tags", "origin"])
    result = send(client, current, query)
    assert result["question"] == current["question"]
    assert result["facts"] == current["facts"]
    assert "[A-CONDITION]" in result["reply"]
    case = db_session.scalar(
        select(ReturnCaseRecord).where(ReturnCaseRecord.session_id == UUID(current["session_id"]))
    )
    assert case.field_observations.get("_clarification_attempts", 0) == 0


def test_uncertainty_is_localized_then_two_failed_clarifications_escalate(checklist):
    client, script, _ = checklist
    text = "I am not sure."
    script[text] = interpretation(text, kind="uncertain")
    current = send(client, start(client), text)
    assert not current["support_ticket"]
    assert "Which condition" in current["reply"]
    assert all(
        f not in current["facts"] for f in ("stained", "damaged", "tags_attached", "tags_intact")
    )
    current = send(client, current, text)
    assert not current["support_ticket"]
    current = send(client, current, text)
    assert current["state"] == "escalated"


def test_reported_exception_cannot_be_erased_by_button_or_global_statement(checklist):
    client, script, _ = checklist
    text = "The tags are removed."
    script[text] = interpretation(
        text, kind="exception", facts=[fact("tags_attached", False, text)]
    )
    current = send(client, start(client), text)
    collective = "All clear and submit my return."
    script[collective] = interpretation(collective, kind="all_clear", submit=True)
    result = send(client, current, collective)
    assert not result["return_request"]
    assert result["facts"]["tags_attached"]["value"] is False


def test_dirty_tag_question_has_no_invented_rejection_rule(checklist):
    client, script, _ = checklist
    text = "My tags are dirty. Can I return this?"
    script[text] = interpretation(
        text, kind="exception", question="Can I return this?", topics=["tag_cleanliness"]
    )
    result = send(client, start(client), text)
    assert result["state"] == "escalated" and result["decision"] != "ineligible"
    assert "does not specify" in result["reply"]


def test_snapshot_refresh_and_changed_item_block_old_scope(checklist, db_session):
    client, _, _ = checklist
    current = start(client)
    restored = client.get(f"/api/v1/return-cases/{current['session_id']}").json()
    assert restored["question"] == current["question"]
    case = db_session.scalar(
        select(ReturnCaseRecord).where(ReturnCaseRecord.session_id == UUID(current["session_id"]))
    )
    case.field_observations = {
        **case.field_observations,
        "_checklist": {
            **case.field_observations["_checklist"],
            "item_id": str(uuid4()),
        },
    }
    db_session.commit()
    response = client.post(
        f"/api/v1/questions/{current['question']['question_id']}/answer",
        json={
            "session_id": current["session_id"],
            "selected_value": "attest_and_submit",
        },
    )
    assert response.status_code == 409


@pytest.mark.parametrize("text", ["okay", "yes", "嗯", "可以"])
def test_vague_reply_cannot_be_promoted_to_global_submission(checklist, text):
    client, script, _ = checklist
    # Even an over-eager model cannot authorize these context-ambiguous utterances.
    script[text] = interpretation(
        text,
        kind="all_clear",
        submit=True,
        facts=[
            fact("stained", False, text),
            fact("damaged", False, text),
            fact("tags_attached", True, text),
            fact("tags_intact", True, text),
        ],
    )
    result = send(client, start(client), text)
    assert not result["return_request"]
    assert result["decision"] != "eligible"
    assert "stained" not in result["facts"]


def test_specific_unknown_is_not_counted_as_failed_clarification(checklist, db_session):
    client, script, _ = checklist
    uncertain = "I am not sure."
    script[uncertain] = interpretation(uncertain, kind="uncertain")
    current = send(client, start(client), uncertain)
    detail = "I do not know if the tags are attached."
    script[detail] = interpretation(
        detail,
        kind="uncertain",
        facts=[
            fact("tags_attached", None, detail, "uncertain"),
        ],
    )
    result = send(client, current, detail)
    case = db_session.scalar(
        select(ReturnCaseRecord).where(ReturnCaseRecord.session_id == UUID(result["session_id"]))
    )
    assert case.field_observations["_clarification_attempts"] == 0
    assert result["facts"]["tags_attached"]["state"] == "unknown"
    assert not result["support_ticket"]


def test_collective_declaration_cannot_invent_missing_evidence_or_authorization(checklist):
    client, script, _ = checklist
    text = "None of those problems apply."
    body = interpretation(text, kind="all_clear", submit=True)
    body["checklist_reply"]["submit_evidence"] = "submit my return"
    script[text] = body
    result = send(client, start(client), text)
    assert not result["return_request"]
    assert result["question"]["field"] == "confirm_return"


def test_repeated_uncertain_buttons_do_not_loop_forever(checklist):
    client, _, _ = checklist
    current = answer(client, start(client), "uncertain")
    assert not current["support_ticket"]
    current = answer(client, current, "uncertain")
    assert not current["support_ticket"]
    current = answer(client, current, "uncertain")
    assert current["state"] == "escalated"


def test_pure_hypothetical_tag_cleanliness_question_keeps_checklist(checklist):
    client, script, _ = checklist
    current = start(client)
    text = "What if the tags are dirty?"
    script[text] = interpretation(text, question=text, topics=["tag_cleanliness"])
    result = send(client, current, text)
    assert result["question"] == current["question"]
    assert not result["support_ticket"]
    assert "does not specify" in result["reply"]


def test_reported_dirty_tag_without_question_also_has_safe_policy_gap_routing(checklist):
    client, script, _ = checklist
    text = "The tags are dirty."
    script[text] = interpretation(text, kind="exception", topics=["tag_cleanliness"])
    result = send(client, start(client), text)
    assert result["state"] == "escalated" and "does not specify" in result["reply"]


def test_unanswered_origin_clarification_also_stops_after_two_attempts(checklist):
    client, script, _ = checklist
    text = "The tags are removed."
    script[text] = interpretation(
        text, kind="exception", facts=[fact("tags_attached", False, text)]
    )
    result = send(client, start(client), text)
    assert result["question"]["field"] == "condition_origin"
    result = send(client, result, "hmm")
    assert result["question"]["field"] == "condition_origin"
    result = send(client, result, "hmm")
    assert result["state"] == "escalated"


def test_checklist_cannot_submit_if_it_expires_during_understanding(checklist, db_session):
    client, script, _ = checklist
    current = start(client)
    qid = UUID(current["question"]["question_id"])
    text = "None apply and submit my return."

    def delayed_answer():
        db_session.get(QuestionRequestRecord, qid).expires_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
        return interpretation(text, kind="all_clear", submit=True)

    script[text] = delayed_answer
    response = client.post(
        "/api/v1/chat",
        json={
            "session_id": current["session_id"],
            "message": text,
            "in_reply_to_question_id": str(qid),
        },
    )
    assert response.status_code == 410
    assert db_session.scalar(select(func.count()).select_from(ReturnRequestRecord)) == 0


def test_checklist_answer_is_still_owned_and_cannot_be_used_by_another_account(checklist):
    from scripts.seed_data import stable_id

    client, _, _ = checklist
    current = start(client)
    client.post(
        "/api/v1/demo/session", json={"customer_id": str(stable_id("demo-customer", "bob"))}
    )
    response = client.post(
        f"/api/v1/questions/{current['question']['question_id']}/answer",
        json={
            "session_id": current["session_id"],
            "selected_value": "attest_and_submit",
        },
    )
    assert response.status_code == 404


def test_legacy_pending_question_is_replaced_but_known_facts_survive(checklist, monkeypatch):
    client, script, _ = checklist
    script["optional reason"] = interpretation(
        "optional reason",
        facts=[
            fact("reason_text", "optional reason", "optional reason"),
        ],
    )
    monkeypatch.setattr(get_settings(), "collection_style", "individual")
    historical = start(client)
    assert historical["question"]["field"] == "reason_text"
    historical = send(client, historical, "optional reason")
    historical = answer(client, historical, "no")
    monkeypatch.setattr(get_settings(), "collection_style", "checklist")
    restored = client.get(f"/api/v1/return-cases/{historical['session_id']}").json()
    assert restored["question"]["field"] == "condition_checklist"
    assert restored["facts"]["stained"]["value"] is False


def test_window_question_uses_pinned_policy_without_causing_condition_interrogation(checklist):
    client, script, _ = checklist
    current = start(client)
    text = "What is the return deadline?"
    script[text] = interpretation(text, question=text, topics=["window"])
    result = send(client, current, text)
    assert "A-WINDOW" in {c["clause_id"] for c in result["policy_evidence"]}
    assert result["question"] == current["question"]
