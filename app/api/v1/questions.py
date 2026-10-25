from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.presenters import present_case
from app.api.schemas import AnswerRequest, CaseResponse
from app.config import get_settings
from app.db.models import CustomerRecord
from app.db.session import get_db
from app.services.apparel_service import build_apparel_service
from app.services.case_service import CaseService
from app.services.demo_identity import optional_demo_customer

router = APIRouter(prefix="/questions", tags=["questions"])


@router.post("/{question_id}/answer", response_model=CaseResponse)
async def answer_question(
    question_id: UUID,
    payload: AnswerRequest,
    db: Session = Depends(get_db),
    customer: CustomerRecord | None = Depends(optional_demo_customer),
) -> CaseResponse:
    if get_settings().workflow_mode == "apparel":
        assert customer is not None
        return await build_apparel_service(db, customer, get_settings()).answer(
            payload.session_id, question_id, payload.selected_value, payload.free_text
        )
    case, question, request = CaseService(db).answer_question(
        question_id=question_id,
        session_id=payload.session_id,
        selected_value=payload.selected_value,
        free_text=payload.free_text,
    )
    return present_case(case, question, request)
