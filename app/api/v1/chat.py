from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.presenters import present_case
from app.api.schemas import CaseResponse, ChatRequest
from app.config import get_settings
from app.db.session import get_db
from app.extractors.factory import build_extractor
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=CaseResponse)
async def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> CaseResponse:
    service = ConversationService(db, build_extractor(get_settings()))
    case, question, request = await service.handle(
        session_id=payload.session_id,
        message=payload.message,
        customer_email=payload.customer_email,
    )
    response = present_case(case, question, request)
    service.save_assistant_message(payload.session_id, response.reply)
    return response
