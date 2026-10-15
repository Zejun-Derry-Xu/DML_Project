from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models import (
    OrderItemRecord,
    QuestionRequestRecord,
    ReturnCaseRecord,
    ReturnRequestRecord,
)
from app.domain.models import (
    CaseStatus,
    OrderSnapshot,
    PolicyResult,
    QuestionField,
    QuestionOption,
    ReturnDecision,
    ReturnReason,
)
from app.domain.policy_engine import evaluate_return
from app.domain.reason_codes import ReasonCode
from app.domain.state_machine import build_question
from app.errors import AppError
from app.repositories.order_repository import OrderRepository
from app.repositories.return_repository import ReturnRepository
from app.services.order_service import OrderService


class CaseService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.returns = ReturnRepository(session)
        self.orders = OrderService(OrderRepository(session))

    def advance(
        self,
        *,
        session_id: UUID,
        customer_email: str | None = None,
        order_number: str | None = None,
        item_id: UUID | None = None,
        reason: ReturnReason | None = None,
        used: bool | None = None,
        opened: bool | None = None,
        damaged: bool | None = None,
        wants_human: bool = False,
        stained: bool | None = None,
        tags_attached: bool | None = None,
        tags_intact: bool | None = None,
        condition_origin: Literal["customer", "pre_existing", "unknown"] | None = None,
    ) -> tuple[ReturnCaseRecord, QuestionRequestRecord | None, ReturnRequestRecord | None]:
        case = self.returns.get_or_create_case(session_id)
        if case.status in {"return_created", "escalated", "cancelled"} or (
            case.status == "closed" and case.policy_version != "mvp-2.0.0"
        ):
            return case, None, case.return_request
        self._upgrade_policy(case)
        for field, value in (
            ("stained", stained),
            ("tags_attached", tags_attached),
            ("tags_intact", tags_intact),
            ("condition_origin", condition_origin),
        ):
            if value is not None:
                previous = getattr(case, field)
                if previous is not None and previous != value:
                    return self._escalate_conflict(case)
                setattr(case, field, value)
        if customer_email:
            case_email = case.customer_email
            if case_email and case_email.casefold() != customer_email.casefold():
                return self._escalate_conflict(case)
            case.customer_email = customer_email
        if order_number:
            normalized = order_number.upper()
            if case.order_number and case.order_number != normalized:
                return self._escalate_conflict(case)
            case.order_number = normalized
        if item_id:
            if case.item_id and case.item_id != item_id:
                return self._escalate_conflict(case)
            case.item_id = item_id
        if reason:
            if case.reason and case.reason != reason.value:
                return self._escalate_conflict(case)
            case.reason = reason.value
        if used is not None:
            if case.used is not None and case.used != used:
                return self._escalate_conflict(case)
            case.used = used
        if opened is not None:
            if case.opened is not None and case.opened != opened:
                return self._escalate_conflict(case)
            case.opened = opened
        if damaged is not None:
            if case.damaged is not None and case.damaged != damaged:
                return self._escalate_conflict(case)
            case.damaged = damaged

        if wants_human:
            case.status = CaseStatus.ESCALATED.value
            case.decision = ReturnDecision.HUMAN_REVIEW.value
            case.decision_reason = ReasonCode.USER_REQUESTED_HUMAN.value
            case.pending_question = None
            self.returns.replace_pending_questions(session_id)
            self.session.commit()
            return case, None, None

        if not case.order_number:
            question = self._persist_question(case, "order_id")
            self.session.commit()
            return case, question, None
        email = getattr(case, "customer_email", None)
        if not email:
            raise AppError("MISSING_EMAIL", "A customer email is required to access an order.", 422)
        order = self.orders.lookup(case.order_number, email)
        case.order_id = order.id
        if case.item_id is None and len(order.items) > 1:
            choices = [
                QuestionOption(value=str(item.id), label=item.product_name) for item in order.items
            ]
            question = self._persist_question(case, "item_id", choices)
            self.session.commit()
            return case, question, None
        item = self.orders.select_item(order, case.item_id)
        case.item_id = item.id
        case.item_name = item.product_name

        result = evaluate_return(
            order,
            item,
            reason=ReturnReason(case.reason) if case.reason else None,
            used=case.used,
            damaged=case.damaged,
            stained=case.stained,
            tags_attached=case.tags_attached,
            tags_intact=case.tags_intact,
            condition_origin=case.condition_origin,
        )
        return self._apply_policy_result(case, order, result)

    def answer_question(
        self,
        *,
        question_id: UUID,
        session_id: UUID,
        selected_value: str | None,
        free_text: str | None,
    ) -> tuple[ReturnCaseRecord, QuestionRequestRecord | None, ReturnRequestRecord | None]:
        question = self.returns.question(question_id)
        if question is None:
            raise AppError("QUESTION_NOT_FOUND", "The question could not be found.", 404)
        if question.session_id != session_id:
            raise AppError(
                "QUESTION_SESSION_MISMATCH", "This question belongs to another session.", 403
            )
        if question.status != "pending":
            raise AppError("QUESTION_ALREADY_RESOLVED", "This question is no longer pending.", 409)
        expires_at = question.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            question.status = "expired"
            self.session.commit()
            raise AppError("QUESTION_EXPIRED", "This question has expired. Resume the case.", 410)
        case = self.returns.case_by_session(session_id)
        if case is None:
            raise AppError("CASE_NOT_FOUND", "The return case could not be found.", 404)
        if self._upgrade_policy(case):
            self.session.commit()
            raise AppError(
                "STALE_ANSWER", "Policy changed; resume to answer current questions.", 409
            )
        if question.case_version != case.version:
            question.status = "replaced"
            self.session.commit()
            raise AppError("STALE_ANSWER", "This answer targets an older case version.", 409)
        allowed = {str(option["value"]) for option in question.options}
        if selected_value is None or selected_value not in allowed:
            if not (question.allow_free_text and free_text):
                raise AppError("INVALID_ANSWER", "Select one of the current question options.", 422)
            raise AppError(
                "FREE_TEXT_REQUIRES_CHAT",
                "Free-text answers must be submitted through the chat endpoint.",
                422,
            )

        question.status = "answered"
        question.selected_value = selected_value
        question.free_text = free_text
        question.answered_at = datetime.now(UTC)
        case.pending_question = None
        case.version += 1

        if question.field == "confirm_return":
            if selected_value == "cancel":
                case.status = CaseStatus.CANCELLED.value
                self.session.commit()
                return case, None, None
            request = self.create_return_request(case, idempotency_key=str(question.id))
            case.status = CaseStatus.RETURN_CREATED.value
            self.session.commit()
            return case, None, request

        if question.field == "order_id":
            self.session.flush()
            return self.advance(session_id=session_id, order_number=selected_value)
        if question.field == "item_id":
            self.session.flush()
            return self.advance(session_id=session_id, item_id=UUID(selected_value))
        if question.field == "reason":
            self.session.flush()
            return self.advance(session_id=session_id, reason=ReturnReason(selected_value))
        if question.field == "condition_origin":
            self.session.flush()
            return self.advance(
                session_id=session_id,
                condition_origin=cast(
                    Literal["customer", "pre_existing", "unknown"], selected_value
                ),
            )
        if question.field in {
            "used",
            "opened",
            "stained",
            "tags_attached",
            "tags_intact",
            "damaged",
        }:
            if selected_value == "unknown" and question.field in {
                "stained",
                "tags_attached",
                "tags_intact",
                "damaged",
            }:
                case.decision = ReturnDecision.HUMAN_REVIEW.value
                case.decision_reason = ReasonCode.CONDITION_REQUIRES_REVIEW.value
                case.status = CaseStatus.ESCALATED.value
                self.returns.replace_pending_questions(session_id)
                self.session.commit()
                return case, None, None
            bool_value = None if selected_value == "unknown" else selected_value == "yes"
            self.session.flush()
            values: dict[str, Any] = {question.field: bool_value}
            return self.advance(session_id=session_id, **values)
        raise AppError("INVALID_QUESTION", "The question field is not supported.", 422)

    def resume(
        self, session_id: UUID
    ) -> tuple[ReturnCaseRecord, QuestionRequestRecord | None, ReturnRequestRecord | None]:
        case = self.returns.case_by_session(session_id)
        if case is None:
            raise AppError("CASE_NOT_FOUND", "The return case could not be found.", 404)
        if case.status in {
            CaseStatus.RETURN_CREATED.value,
            CaseStatus.CLOSED.value,
            CaseStatus.ESCALATED.value,
            CaseStatus.CANCELLED.value,
        }:
            return case, None, case.return_request
        if self._upgrade_policy(case):
            self.session.flush()
            return self.advance(session_id=session_id)
        pending = self.returns.pending_question(session_id)
        if pending:
            expires_at = pending.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at > datetime.now(UTC):
                return case, pending, case.return_request
            pending.status = "expired"
            case.pending_question = None
            self.session.flush()
        return self.advance(session_id=session_id)

    def _apply_policy_result(
        self, case: ReturnCaseRecord, order: OrderSnapshot, result: PolicyResult
    ) -> tuple[ReturnCaseRecord, QuestionRequestRecord | None, ReturnRequestRecord | None]:
        case.decision = result.decision.value
        case.decision_reason = result.reason_code.value
        if result.decision == ReturnDecision.NEED_MORE_INFORMATION:
            fields: dict[ReasonCode, QuestionField] = {
                ReasonCode.MISSING_RETURN_REASON: "reason",
                ReasonCode.MISSING_USAGE_STATUS: "used",
                ReasonCode.MISSING_STAIN_STATUS: "stained",
                ReasonCode.MISSING_TAG_ATTACHMENT: "tags_attached",
                ReasonCode.MISSING_TAG_INTEGRITY: "tags_intact",
                ReasonCode.MISSING_DAMAGE_STATUS: "damaged",
                ReasonCode.MISSING_CONDITION_ORIGIN: "condition_origin",
            }
            field = fields[result.reason_code]
            question = self._persist_question(case, field)
            self.session.commit()
            return case, question, None
        if result.decision == ReturnDecision.ELIGIBLE:
            case.status = CaseStatus.ELIGIBLE.value
            question = self._persist_question(case, "confirm_return")
            self.session.commit()
            return case, question, None
        case.pending_question = None
        self.returns.replace_pending_questions(case.session_id)
        case.status = (
            CaseStatus.ESCALATED.value
            if result.decision == ReturnDecision.HUMAN_REVIEW
            else CaseStatus.CLOSED.value
        )
        self.session.commit()
        return case, None, None

    def _persist_question(
        self,
        case: ReturnCaseRecord,
        field: QuestionField,
        item_options: list[QuestionOption] | None = None,
    ) -> QuestionRequestRecord:
        existing = self.returns.pending_question(case.session_id)
        if existing and existing.field == field and existing.case_version == case.version:
            return existing
        self.returns.replace_pending_questions(case.session_id)
        question = build_question(
            field,
            case_version=case.version,
            item_options=item_options,
        )
        record = QuestionRequestRecord(
            id=question.question_id,
            session_id=case.session_id,
            return_case_id=case.id,
            field=question.field,
            prompt=question.prompt,
            options=[option.model_dump() for option in question.options],
            allow_free_text=question.allow_free_text,
            status=question.status.value,
            case_version=question.case_version,
            expires_at=question.expires_at,
        )
        self.session.add(record)
        case.pending_question = field
        case.status = CaseStatus.AWAITING_USER.value
        self.session.flush()
        return record

    def _upgrade_policy(self, case: ReturnCaseRecord) -> bool:
        if case.policy_version == "mvp-2.0.0" or case.status in {
            "return_created",
            "closed",
            "escalated",
            "cancelled",
        }:
            return False
        self.returns.replace_pending_questions(case.session_id)
        case.policy_version = "mvp-2.0.0"
        case.version += 1
        case.pending_question = None
        case.decision = None
        case.decision_reason = None
        case.status = CaseStatus.STARTED.value
        return True

    def cancel(self, session_id: UUID) -> tuple[ReturnCaseRecord, None, ReturnRequestRecord | None]:
        case = self.returns.get_or_create_case(session_id)
        if case.status in {"return_created", "closed", "escalated", "cancelled"}:
            return case, None, case.return_request
        case.status = CaseStatus.CANCELLED.value
        case.decision = None
        case.decision_reason = None
        case.pending_question = None
        case.version += 1
        self.returns.replace_pending_questions(session_id)
        self.session.commit()
        return case, None, None

    def clarify(
        self, session_id: UUID, field: QuestionField
    ) -> tuple[ReturnCaseRecord, QuestionRequestRecord, None]:
        case = self.returns.get_or_create_case(session_id)
        self._upgrade_policy(case)
        case.decision = ReturnDecision.NEED_MORE_INFORMATION.value
        case.decision_reason = ReasonCode.INFORMATION_CONFLICT.value
        case.version += 1
        question = self._persist_question(case, field)
        question.prompt = "I found conflicting information. Please confirm: " + question.prompt
        self.session.commit()
        return case, question, None

    def _escalate_conflict(self, case: ReturnCaseRecord) -> tuple[ReturnCaseRecord, None, None]:
        case.decision = ReturnDecision.HUMAN_REVIEW.value
        case.decision_reason = ReasonCode.INFORMATION_CONFLICT.value
        case.status = CaseStatus.ESCALATED.value
        case.pending_question = None
        self.returns.replace_pending_questions(case.session_id)
        self.session.commit()
        return case, None, None

    def create_return_request(
        self, case: ReturnCaseRecord, *, idempotency_key: str
    ) -> ReturnRequestRecord:
        existing = self.returns.return_request_by_key(idempotency_key)
        if existing:
            return existing
        existing = self.returns.return_request_for_case(case.id)
        if existing:
            return existing
        if self._upgrade_policy(case):
            self.session.commit()
            raise AppError(
                "STALE_ANSWER", "Policy changed; resume the case before confirming.", 409
            )
        if not case.order_id or not case.item_id or case.decision != ReturnDecision.ELIGIBLE.value:
            raise AppError("RETURN_NOT_ELIGIBLE", "The case is not ready for return creation.", 409)
        # Claim the item atomically, including when another session confirmed after
        # this case was evaluated. A per-case idempotency key alone cannot do this.
        claimed = self.session.execute(
            update(OrderItemRecord)
            .where(OrderItemRecord.id == case.item_id, OrderItemRecord.return_status.is_(None))
            .values(return_status="requested")
            .returning(OrderItemRecord.id)
        ).scalar_one_or_none()
        if claimed is None:
            raise AppError("ORDER_ALREADY_RETURNED", "A return already exists for this item.", 409)
        request = ReturnRequestRecord(
            rma_number=f"RMA-{str(case.session_id).split('-')[0].upper()}",
            return_case_id=case.id,
            order_id=case.order_id,
            item_id=case.item_id,
            idempotency_key=idempotency_key,
            status="requested",
        )
        self.session.add(request)
        self.session.flush()
        return request
