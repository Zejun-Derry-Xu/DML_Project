from app.api.schemas import (
    CaseResponse,
    PolicyCitation,
    QuestionOptionResponse,
    QuestionResponse,
    ReturnRequestResponse,
)
from app.db.models import QuestionRequestRecord, ReturnCaseRecord, ReturnRequestRecord
from app.observability.metrics import DECISIONS
from app.policy.corpus import load_policy
from app.policy.retrieval import LexicalPolicyRetriever

REPLIES = {
    "eligible": "Based on the information provided, this item is eligible for return.",
    "ineligible": "This item is not eligible for return under the current policy.",
    "human_review": "This case needs review by a human support specialist.",
    "return_created": "Your return request has been created.",
    "cancelled": "The return request was cancelled.",
}


def present_case(
    case: ReturnCaseRecord,
    question: QuestionRequestRecord | None = None,
    return_request: ReturnRequestRecord | None = None,
) -> CaseResponse:
    if case.decision:
        DECISIONS.labels(
            decision=case.decision, reason_code=case.decision_reason or "UNKNOWN"
        ).inc()
    question_response = None
    if question:
        question_response = QuestionResponse(
            question_id=question.id,
            field=question.field,
            prompt=question.prompt,
            options=[QuestionOptionResponse(**option) for option in question.options],
            allow_free_text=question.allow_free_text,
            status=question.status,
            expires_at=question.expires_at,
        )
    request_response = None
    if return_request:
        request_response = ReturnRequestResponse(
            id=return_request.id,
            rma_number=return_request.rma_number,
            status=return_request.status,
            created_at=return_request.created_at,
        )
    if question_response:
        reply = question_response.prompt
    elif case.status == "return_created":
        reply = REPLIES["return_created"]
    elif case.status == "cancelled":
        reply = REPLIES["cancelled"]
    else:
        reply = REPLIES.get(case.decision or "", "Your return case is ready.")
    policy_evidence: list[PolicyCitation] = []
    policy_version = None
    policy_warning = None
    if case.decision_reason and case.status != "cancelled":
        try:
            corpus = load_policy(case.policy_version)
            clauses = LexicalPolicyRetriever(corpus).search(
                "", reason_code=case.decision_reason, limit=len(corpus.clauses)
            )
            policy_evidence = [
                PolicyCitation(
                    clause_id=clause.id,
                    policy_version=corpus.version,
                    scope=clause.scope,
                    content=clause.content,
                )
                for clause in clauses
            ]
            policy_version = corpus.version if policy_evidence else None
            if not policy_evidence:
                policy_warning = "No policy clause is mapped to this case reason."
        except (OSError, ValueError, KeyError, TypeError):
            policy_warning = "Policy evidence is temporarily unavailable."
    return CaseResponse(
        session_id=case.session_id,
        state=case.status,
        decision=case.decision,
        reason_code=case.decision_reason,
        reply=reply,
        question=question_response,
        return_request=request_response,
        policy_version=policy_version,
        policy_evidence=policy_evidence,
        policy_warning=policy_warning,
    )
