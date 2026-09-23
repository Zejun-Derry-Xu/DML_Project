from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.reason_codes import ReasonCode


class ReturnReason(StrEnum):
    DEFECTIVE = "defective"
    WRONG_ITEM = "wrong_item"
    CHANGED_MIND = "changed_mind"
    DOES_NOT_FIT = "does_not_fit"
    OTHER = "other"


class ReturnDecision(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    NEED_MORE_INFORMATION = "need_more_information"
    HUMAN_REVIEW = "human_review"


class CaseStatus(StrEnum):
    STARTED = "started"
    AWAITING_USER = "awaiting_user"
    ELIGIBLE = "eligible"
    CLOSED = "closed"
    ESCALATED = "escalated"
    RETURN_CREATED = "return_created"
    CANCELLED = "cancelled"


class QuestionStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"
    EXPIRED = "expired"
    REPLACED = "replaced"
    CANCELLED = "cancelled"


class ReturnFacts(BaseModel):
    intent: Literal["return", "not_return", "unclear"] = "unclear"
    order_id: str | None = None
    item_name: str | None = None
    reason: ReturnReason | None = None
    used: bool | None = None
    opened: bool | None = None
    damaged: bool | None = None
    wants_human: bool = False


class ReturnCase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: UUID
    customer_email: str | None = None
    order_id: UUID | None = None
    order_number: str | None = None
    item_id: UUID | None = None
    item_name: str | None = None
    reason: ReturnReason | None = None
    used: bool | None = None
    opened: bool | None = None
    damaged: bool | None = None
    pending_question: str | None = None
    decision: ReturnDecision | None = None
    decision_reason: ReasonCode | None = None
    status: CaseStatus = CaseStatus.STARTED
    version: int = 1


class OrderItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_name: str
    price: Decimal
    final_sale: bool = False
    return_status: str | None = None


class OrderSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_number: str
    customer_email: str
    status: str
    ordered_at: datetime
    delivered_at: datetime | None = None
    items: list[OrderItem]


class PolicyResult(BaseModel):
    decision: ReturnDecision
    reason_code: ReasonCode


class QuestionOption(BaseModel):
    value: str
    label: str
    description: str | None = None


class QuestionRequest(BaseModel):
    question_id: UUID = Field(default_factory=uuid4)
    field: Literal["order_id", "item_id", "reason", "used", "opened", "confirm_return"]
    prompt: str
    options: list[QuestionOption]
    selection_mode: Literal["single"] = "single"
    allow_free_text: bool = False
    status: QuestionStatus = QuestionStatus.PENDING
    expires_at: datetime
    case_version: int


class ReturnRequestResult(BaseModel):
    id: UUID
    rma_number: str
    status: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
