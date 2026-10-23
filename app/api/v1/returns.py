from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.api.presenters import present_case
from app.api.schemas import CaseResponse, CreateReturnRequest, EvaluateRequest
from app.config import get_settings
from app.db.models import CustomerRecord
from app.db.session import get_db
from app.errors import AppError
from app.services.apparel_service import ApparelService
from app.services.case_service import CaseService
from app.services.demo_identity import optional_demo_customer

router = APIRouter(tags=["returns"])


@router.post("/returns/evaluate", response_model=CaseResponse)
def evaluate_return(payload: EvaluateRequest, db: Session = Depends(get_db)) -> CaseResponse:
    if get_settings().workflow_mode == "apparel":
        raise AppError("USE_CONVERSATION", "Use the owned conversation and question APIs.", 409)
    case, question, request = CaseService(db).advance(**payload.model_dump())
    return present_case(case, question, request)


@router.post("/returns", response_model=CaseResponse)
def create_return(
    payload: CreateReturnRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    customer: CustomerRecord | None = Depends(optional_demo_customer),
) -> CaseResponse:
    if get_settings().workflow_mode == "apparel":
        assert customer is not None
        service = ApparelService(db, customer, get_settings())
        owned_case = service.owned(payload.session_id)
        confirmation = service.returns.question(payload.confirmation_question_id)
        if (
            owned_case.status == "return_created"
            and confirmation
            and confirmation.session_id == owned_case.session_id
            and confirmation.field == "confirm_return"
            and confirmation.selected_value == "confirm"
        ):
            return service.response(owned_case)
        raise AppError("CONFIRMATION_REQUIRED", "Answer the current confirmation card first.", 409)
    legacy_service = CaseService(db)
    case = legacy_service.returns.case_by_session(payload.session_id)
    if case is None:
        raise AppError("CASE_NOT_FOUND", "The return case could not be found.", 404)
    if case.status == "return_created" and case.return_request:
        return present_case(case, return_request=case.return_request)
    confirmation = legacy_service.returns.question(payload.confirmation_question_id)
    if (
        confirmation is None
        or confirmation.session_id != payload.session_id
        or confirmation.field != "confirm_return"
        or confirmation.case_version != case.version
        or confirmation.status != "answered"
        or confirmation.selected_value != "confirm"
    ):
        raise AppError(
            "CONFIRMATION_REQUIRED",
            "An answered confirmation question is required before creating a return.",
            409,
        )
    request = legacy_service.create_return_request(case, idempotency_key=idempotency_key)
    case.status = "return_created"
    db.commit()
    return present_case(case, return_request=request)


@router.get("/return-cases/{session_id}", response_model=CaseResponse)
def get_return_case(
    session_id: UUID,
    db: Session = Depends(get_db),
    customer: CustomerRecord | None = Depends(optional_demo_customer),
) -> CaseResponse:
    if get_settings().workflow_mode == "apparel":
        assert customer is not None
        return ApparelService(db, customer, get_settings()).resume(session_id)
    case, question, request = CaseService(db).resume(session_id)
    return present_case(case, question, request)


@router.post("/return-cases/{session_id}/resume", response_model=CaseResponse)
def resume_return_case(
    session_id: UUID,
    db: Session = Depends(get_db),
    customer: CustomerRecord | None = Depends(optional_demo_customer),
) -> CaseResponse:
    if get_settings().workflow_mode == "apparel":
        assert customer is not None
        return ApparelService(db, customer, get_settings()).resume(session_id)
    case, question, request = CaseService(db).resume(session_id)
    return present_case(case, question, request)
