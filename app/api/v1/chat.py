from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.presenters import present_case
from app.api.schemas import CaseResponse, ChatRequest
from app.config import get_settings
from app.db.models import CustomerRecord
from app.db.session import get_db
from app.extractors.factory import build_extractor
from app.services.apparel_service import ApparelService
from app.services.conversation_service import ConversationService
from app.services.demo_identity import optional_demo_customer

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=CaseResponse)
async def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    customer: CustomerRecord | None = Depends(optional_demo_customer),
) -> CaseResponse:
    if get_settings().workflow_mode == "apparel":
        assert customer is not None
        return await ApparelService(db, customer, get_settings()).chat(
            payload.session_id, payload.message
        )
    service = ConversationService(db, build_extractor(get_settings()))
    case, question, request = await service.handle(
        session_id=payload.session_id,
        message=payload.message,
        customer_email=payload.customer_email,
    )
    response = present_case(case, question, request)
    service.save_assistant_message(payload.session_id, response.reply)
    return response
