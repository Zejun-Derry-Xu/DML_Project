from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.presenters import present_case
from app.api.schemas import AnswerRequest, CaseResponse
from app.db.session import get_db
from app.services.case_service import CaseService

router = APIRouter(prefix="/questions", tags=["questions"])


@router.post("/{question_id}/answer", response_model=CaseResponse)
def answer_question(
    question_id: UUID, payload: AnswerRequest, db: Session = Depends(get_db)
) -> CaseResponse:
    case, question, request = CaseService(db).answer_question(
        question_id=question_id,
        session_id=payload.session_id,
        selected_value=payload.selected_value,
        free_text=payload.free_text,
    )
    return present_case(case, question, request)
