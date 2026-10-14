import json

from app.evaluation.return_policy import FIXTURE, facts_for, model_payload, rule_decision
from app.policy.corpus import load_policy


def test_boundary_labels_are_independent_and_cover_four_outcomes():
    rows = json.loads(FIXTURE.read_text())
    assert {row["expected_decision"] for row in rows} == {
        "eligible",
        "ineligible",
        "need_more_information",
        "human_review",
    }
    for row in rows:
        assert rule_decision(facts_for(row))[0] == row["expected_decision"]


def test_reader_prompt_contains_facts_and_policy_but_no_answer_labels():
    row = {"days": 31, "expected_decision": "ineligible", "expected_clause": "P-WINDOW"}
    facts = facts_for(row)
    payload = model_payload(facts, list(load_policy().clauses), "fake-model")
    text = json.dumps(payload["messages"])
    assert "expected_decision" not in text
    assert "expected_clause" not in text
    assert '"days_since_delivery": 31' in payload["messages"][1]["content"]
