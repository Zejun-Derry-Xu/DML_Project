from datetime import datetime
from decimal import Decimal
from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from app.domain.models import ReturnReason


class OrderItemResponse(BaseModel):
    id: UUID
    product_name: str
    price: Decimal
    final_sale: bool
    return_status: str | None


class OrderResponse(BaseModel):
    id: UUID
    order_number: str
    status: str
    ordered_at: datetime
    delivered_at: datetime | None
    items: list[OrderItemResponse]


class QuestionOptionResponse(BaseModel):
    value: str
    label: str
    description: str | None = None


class QuestionResponse(BaseModel):
    question_id: UUID
    field: str
    prompt: str
    options: list[QuestionOptionResponse]
    selection_mode: str = "single"
    allow_free_text: bool
    status: str
    expires_at: datetime


class ReturnRequestResponse(BaseModel):
    id: UUID
    rma_number: str
    status: str
    created_at: datetime


class CaseResponse(BaseModel):
    session_id: UUID
    state: str
    decision: str | None
    reason_code: str | None
    reply: str
    question: QuestionResponse | None = None
    return_request: ReturnRequestResponse | None = None
    request_id: UUID = Field(default_factory=uuid4)


class EvaluateRequest(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    customer_email: str | None = None
    order_number: str | None = None
    item_id: UUID | None = None
    reason: ReturnReason | None = None
    used: bool | None = None
    opened: bool | None = None
    damaged: bool | None = None
    wants_human: bool = False


class AnswerRequest(BaseModel):
    session_id: UUID
    selected_value: str | None = None
    free_text: str | None = None

    @model_validator(mode="after")
    def requires_an_answer(self) -> Self:
        if self.selected_value is None and not self.free_text:
            raise ValueError("selected_value or free_text is required")
        return self


class CreateReturnRequest(BaseModel):
    session_id: UUID
    confirmation_question_id: UUID
