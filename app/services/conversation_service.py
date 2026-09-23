from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import (
    MessageRecord,
    QuestionRequestRecord,
    ReturnCaseRecord,
    ReturnRequestRecord,
    ToolCallRecord,
)
from app.domain.models import ReturnCase, ReturnDecision, ReturnFacts, ReturnReason
from app.extractors.base import FactExtractor
from app.repositories.order_repository import OrderRepository
from app.repositories.return_repository import ReturnRepository
from app.services.case_service import CaseService


class ConversationService:
    def __init__(self, session: Session, extractor: FactExtractor) -> None:
        self.session = session
        self.extractor = extractor
        self.returns = ReturnRepository(session)
        self.cases = CaseService(session)

    async def handle(
        self, *, session_id: UUID, message: str, customer_email: str | None
    ) -> tuple[ReturnCaseRecord, QuestionRequestRecord | None, ReturnRequestRecord | None]:
        record = self.returns.case_by_session(session_id)
        current = self._domain_case(record, session_id)
        pending = self.returns.pending_question(session_id) if record else None
        self.session.add(MessageRecord(session_id=session_id, role="user", content=message))

        if pending and pending.field == "confirm_return":
            normalized = message.strip().casefold().rstrip(".!?")
            if normalized in {"confirm", "confirm return", "yes"}:
                return self.cases.answer_question(
                    question_id=pending.id,
                    session_id=session_id,
                    selected_value="confirm",
                    free_text=message,
                )
            if normalized in {"cancel", "no", "never mind", "nevermind"}:
                return self.cases.answer_question(
                    question_id=pending.id,
                    session_id=session_id,
                    selected_value="cancel",
                    free_text=message,
                )

        started = perf_counter()
        facts = await self.extractor.extract(
            message, current, pending.field if pending else current.pending_question
        )
        latency_ms = round((perf_counter() - started) * 1000)
        self.session.add(
            ToolCallRecord(
                session_id=session_id,
                tool_name="fact_extractor",
                arguments={
                    "message_length": len(message),
                    "pending_question": current.pending_question,
                },
                result={"fields_present": self._present_fields(facts)},
                success=True,
                latency_ms=latency_ms,
            )
        )

        effective_email = customer_email or current.customer_email
        effective_order = facts.order_id or current.order_number
        matched_item_id = self._match_item(effective_order, effective_email, facts.item_name)

        if (
            pending
            and self._pending_answer_value(pending.field, facts, matched_item_id) is not None
        ):
            pending.status = "answered"
            pending.selected_value = self._pending_answer_value(
                pending.field, facts, matched_item_id
            )
            pending.free_text = message
            pending.answered_at = datetime.now(UTC)
            if record:
                record.pending_question = None
                record.version += 1

        return self.cases.advance(
            session_id=session_id,
            customer_email=effective_email,
            order_number=facts.order_id,
            item_id=matched_item_id,
            reason=facts.reason,
            used=facts.used,
            opened=facts.opened,
            damaged=facts.damaged,
            wants_human=facts.wants_human,
        )

    def save_assistant_message(self, session_id: UUID, reply: str) -> None:
        self.session.add(MessageRecord(session_id=session_id, role="assistant", content=reply))
        self.session.commit()

    def _match_item(
        self, order_number: str | None, email: str | None, item_name: str | None
    ) -> UUID | None:
        if not order_number or not email or not item_name:
            return None
        record = OrderRepository(self.session).by_number(order_number)
        if record is None or record.customer.email.casefold() != email.casefold():
            return None
        candidate = self._normalize(item_name)
        matches = [
            item.id
            for item in record.items
            if candidate in self._normalize(item.product_name)
            or self._normalize(item.product_name) in candidate
        ]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _normalize(value: str) -> str:
        return "".join(character for character in value.casefold() if character.isalnum())

    @staticmethod
    def _pending_answer_value(field: str, facts: ReturnFacts, item_id: UUID | None) -> str | None:
        if field == "order_id":
            return facts.order_id
        if field == "item_id":
            return str(item_id) if item_id else None
        if field == "reason":
            return facts.reason.value if facts.reason else None
        if field == "used" and facts.used is not None:
            return "yes" if facts.used else "no"
        if field == "opened" and facts.opened is not None:
            return "yes" if facts.opened else "no"
        return None

    @staticmethod
    def _present_fields(facts: ReturnFacts) -> list[str]:
        data = facts.model_dump()
        return [
            key
            for key, value in data.items()
            if value is not None and value is not False and value != "unclear"
        ]

    @staticmethod
    def _domain_case(record: ReturnCaseRecord | None, session_id: UUID) -> ReturnCase:
        if record is None:
            return ReturnCase(session_id=session_id)
        return ReturnCase(
            session_id=record.session_id,
            customer_email=record.customer_email,
            order_id=record.order_id,
            order_number=record.order_number,
            item_id=record.item_id,
            item_name=record.item_name,
            reason=ReturnReason(record.reason) if record.reason else None,
            used=record.used,
            opened=record.opened,
            damaged=record.damaged,
            pending_question=record.pending_question,
            decision=ReturnDecision(record.decision) if record.decision else None,
            decision_reason=record.decision_reason,
            status=record.status,
            version=record.version,
        )
