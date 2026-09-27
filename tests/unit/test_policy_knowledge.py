import json
from pathlib import Path

import pytest

from app.services.policy_knowledge import PolicyKnowledge


def test_retrieves_window_with_versioned_citation() -> None:
    answer = PolicyKnowledge().explain("What is the return window?")
    assert answer["status"] == "answered"
    assert answer["policy_version"] == "mvp-1.0.0"
    assert answer["citations"][0]["clause_id"] == "RF-02"


def test_unknown_eligibility_requires_verified_facts() -> None:
    answer = PolicyKnowledge().explain("Am I eligible to return this item?")
    assert answer["status"] == "insufficient_facts"
    assert answer["decision"] is None


def test_no_answer_and_wrong_version() -> None:
    knowledge = PolicyKnowledge()
    assert knowledge.explain("Do you offer price matching?")["status"] == "no_answer"
    assert (
        knowledge.explain(
            "Do you offer price matching?", decision="ineligible", reason_code="FINAL_SALE"
        )["status"]
        == "no_answer"
    )
    assert (
        knowledge.explain("Return window", requested_version="old")["status"] == "version_mismatch"
    )


def test_conflicting_saved_decision_stops_explanation() -> None:
    answer = PolicyKnowledge().explain(
        "This is final sale", decision="eligible", reason_code="FINAL_SALE"
    )
    assert answer["status"] == "conflict"
    assert answer["decision"] is None


def test_eligible_decision_cites_all_applicable_clauses() -> None:
    answer = PolicyKnowledge().explain(
        "Am I eligible?", decision="eligible", reason_code="ELIGIBLE"
    )
    assert answer["status"] == "answered"
    assert {c["clause_id"] for c in answer["citations"]} == {"RF-01", "RF-02", "RF-03", "RF-04"}


def test_document_version_must_match_engine(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"version": "wrong", "clauses": []}))
    with pytest.raises(ValueError, match="versions differ"):
        PolicyKnowledge(path)
