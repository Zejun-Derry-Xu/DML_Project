from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.api.presenters import present_case
from app.api.schemas import CaseResponse, CreateReturnRequest, EvaluateRequest
from app.db.session import get_db
from app.errors import AppError
from app.services.case_service import CaseService

router = APIRouter(tags=["returns"])


@router.post("/returns/evaluate", response_model=CaseResponse)
def evaluate_return(payload: EvaluateRequest, db: Session = Depends(get_db)) -> CaseResponse:
    case, question, request = CaseService(db).advance(**payload.model_dump())
    return present_case(case, question, request)


@router.post("/returns", response_model=CaseResponse)
def create_return(
    payload: CreateReturnRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> CaseResponse:
    service = CaseService(db)
    case = service.returns.case_by_session(payload.session_id)
    if case is None:
        raise AppError("CASE_NOT_FOUND", "The return case could not be found.", 404)
    if case.status == "return_created" and case.return_request:
        return present_case(case, return_request=case.return_request)
    confirmation = service.returns.question(payload.confirmation_question_id)
    if (
        confirmation is None
        or confirmation.session_id != payload.session_id
        or confirmation.field != "confirm_return"
        or confirmation.status != "answered"
        or confirmation.selected_value != "confirm"
    ):
        raise AppError(
            "CONFIRMATION_REQUIRED",
            "An answered confirmation question is required before creating a return.",
            409,
        )
    request = service.create_return_request(case, idempotency_key=idempotency_key)
    case.status = "return_created"
    db.commit()
    return present_case(case, return_request=request)


@router.get("/return-cases/{session_id}", response_model=CaseResponse)
def get_return_case(session_id: UUID, db: Session = Depends(get_db)) -> CaseResponse:
    case, question, request = CaseService(db).resume(session_id)
    return present_case(case, question, request)


@router.post("/return-cases/{session_id}/resume", response_model=CaseResponse)
def resume_return_case(session_id: UUID, db: Session = Depends(get_db)) -> CaseResponse:
    case, question, request = CaseService(db).resume(session_id)
    return present_case(case, question, request)
