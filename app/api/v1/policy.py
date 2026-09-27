from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.errors import AppError
from app.repositories.return_repository import ReturnRepository
from app.services.policy_knowledge import PolicyKnowledge

router = APIRouter(prefix="/policy", tags=["policy"])


class PolicyExplainRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    session_id: UUID | None = None
    customer_email: str | None = None
    requested_version: str | None = None


@router.post("/explain")
def explain_policy(
    payload: PolicyExplainRequest, db: Session = Depends(get_db)
) -> dict[str, object]:
    decision = None
    reason_code = None
    if payload.session_id:
        case = ReturnRepository(db).case_by_session(payload.session_id)
        if case is None:
            raise AppError("CASE_NOT_FOUND", "The return case could not be found.", 404)
        if (
            not payload.customer_email
            or not case.customer_email
            or case.customer_email.casefold() != payload.customer_email.casefold()
        ):
            raise AppError("IDENTITY_MISMATCH", "The customer email does not match this case.", 403)
        decision = case.decision
        reason_code = case.decision_reason
    return PolicyKnowledge().explain(
        payload.question,
        decision=decision,
        reason_code=reason_code,
        requested_version=payload.requested_version,
    )
