"""Local versioned policy retrieval and cited, deterministic explanations."""

import json
import re
from pathlib import Path
from typing import Any

from app.domain.policy_engine import POLICY_VERSION

DOCUMENT = Path(__file__).parents[2] / "docs/policy/mvp-1.0.0.json"
ELIGIBILITY_QUERY = re.compile(r"\b(?:eligible|qualify|can i return|can this be returned)\b", re.I)
CASE_QUERY = re.compile(r"\b(?:return|refund|eligible|qualify|policy|denied|decision|why)\b", re.I)


class PolicyKnowledge:
    def __init__(self, path: Path = DOCUMENT) -> None:
        document = json.loads(path.read_text())
        if document["version"] != POLICY_VERSION:
            raise ValueError("Policy document and engine versions differ")
        self.version: str = document["version"]
        self.clauses: list[dict[str, Any]] = document["clauses"]

    def retrieve(self, question: str, reason_code: str | None = None) -> list[dict[str, Any]]:
        if reason_code == "ELIGIBLE" and CASE_QUERY.search(question):
            return [
                clause
                for clause in self.clauses
                if clause["id"] in {"RF-01", "RF-02", "RF-03", "RF-04"}
            ]
        query = question.casefold()
        scored = []
        for clause in self.clauses:
            score = sum(1 for term in clause["terms"] if term.casefold() in query)
            if CASE_QUERY.search(question) and reason_code in clause["reason_codes"]:
                score += 10
            if score:
                scored.append((score, clause))
        return [clause for _, clause in sorted(scored, key=lambda pair: -pair[0])[:3]]

    def explain(
        self,
        question: str,
        *,
        decision: str | None = None,
        reason_code: str | None = None,
        requested_version: str | None = None,
    ) -> dict[str, Any]:
        if requested_version and requested_version != self.version:
            return {
                "status": "version_mismatch",
                "answer": "The requested policy version is unavailable.",
                "policy_version": self.version,
                "decision": None,
                "citations": [],
            }
        clauses = self.retrieve(question, reason_code)
        citations = [{"clause_id": clause["id"], "text": clause["text"]} for clause in clauses]
        if decision == "need_more_information":
            return {
                "status": "insufficient_facts",
                "answer": "More information is required before the policy engine can decide.",
                "policy_version": self.version,
                "decision": None,
                "citations": citations,
            }
        if reason_code == "USER_REQUESTED_HUMAN" and decision == "human_review":
            return {
                "status": "human_review",
                "answer": "This case has been sent for human review as requested.",
                "policy_version": self.version,
                "decision": "human_review",
                "citations": [],
            }
        if ELIGIBILITY_QUERY.search(question) and decision is None:
            return {
                "status": "insufficient_facts",
                "answer": "I need the verified order and item facts before deciding eligibility.",
                "policy_version": self.version,
                "decision": None,
                "citations": citations,
            }
        if not citations:
            return {
                "status": "no_answer",
                "answer": "The current policy document does not answer that question.",
                "policy_version": self.version,
                "decision": None,
                "citations": [],
            }
        if (
            decision
            and reason_code
            and not any(
                reason_code in clause["reason_codes"] and decision in clause["decisions"]
                for clause in clauses
            )
            and reason_code != "ELIGIBLE"
        ):
            return {
                "status": "conflict",
                "answer": (
                    "The saved decision conflicts with the available policy evidence. "
                    "Human review is required."
                ),
                "policy_version": self.version,
                "decision": None,
                "citations": citations,
            }
        explanation = " ".join(
            f"[{citation['clause_id']}] {citation['text']}" for citation in citations
        )
        return {
            "status": "answered",
            "answer": explanation,
            "policy_version": self.version,
            "decision": decision,
            "citations": citations,
        }
