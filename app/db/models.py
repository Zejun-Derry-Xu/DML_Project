from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.session import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CustomerRecord(TimestampMixin, Base):
    __tablename__ = "customers"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    orders: Mapped[list[OrderRecord]] = relationship(back_populates="customer")


class OrderRecord(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    order_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(30))
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    customer: Mapped[CustomerRecord] = relationship(back_populates="orders")
    items: Mapped[list[OrderItemRecord]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItemRecord(Base):
    __tablename__ = "order_items"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    product_name: Mapped[str] = mapped_column(String(300))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    final_sale: Mapped[bool] = mapped_column(Boolean, default=False)
    return_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    order: Mapped[OrderRecord] = relationship(back_populates="items")


class ReturnCaseRecord(TimestampMixin, Base):
    __tablename__ = "return_cases"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(Uuid, unique=True, index=True)
    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    order_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    item_id: Mapped[UUID | None] = mapped_column(ForeignKey("order_items.id"), nullable=True)
    item_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    used: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    opened: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    damaged: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pending_question: Mapped[str | None] = mapped_column(String(30), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="started")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    questions: Mapped[list[QuestionRequestRecord]] = relationship(back_populates="return_case")
    return_request: Mapped[ReturnRequestRecord | None] = relationship(back_populates="return_case")


class MessageRecord(TimestampMixin, Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)


class QuestionRequestRecord(TimestampMixin, Base):
    __tablename__ = "question_requests"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    return_case_id: Mapped[UUID] = mapped_column(ForeignKey("return_cases.id"), index=True)
    field: Mapped[str] = mapped_column(String(30))
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list[dict[str, str | None]]] = mapped_column(JSON)
    allow_free_text: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    selected_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    free_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_version: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    return_case: Mapped[ReturnCaseRecord] = relationship(back_populates="questions")


class ToolCallRecord(TimestampMixin, Base):
    __tablename__ = "tool_calls"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    tool_name: Mapped[str] = mapped_column(String(100))
    arguments: Mapped[dict[str, object]] = mapped_column(JSON)
    result: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean)
    latency_ms: Mapped[int] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)


class ReturnRequestRecord(TimestampMixin, Base):
    __tablename__ = "return_requests"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    rma_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    return_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("return_cases.id"), unique=True, index=True
    )
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"))
    item_id: Mapped[UUID] = mapped_column(ForeignKey("order_items.id"))
    status: Mapped[str] = mapped_column(String(30), default="requested")
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    return_case: Mapped[ReturnCaseRecord] = relationship(back_populates="return_request")
