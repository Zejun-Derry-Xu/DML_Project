from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import QuestionRequestRecord, ReturnCaseRecord, ReturnRequestRecord


class ReturnRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def case_by_session(self, session_id: UUID) -> ReturnCaseRecord | None:
        statement = (
            select(ReturnCaseRecord)
            .where(ReturnCaseRecord.session_id == session_id)
            .options(
                selectinload(ReturnCaseRecord.questions),
                selectinload(ReturnCaseRecord.return_request),
            )
        )
        return self.session.scalar(statement)

    def get_or_create_case(self, session_id: UUID) -> ReturnCaseRecord:
        case = self.case_by_session(session_id)
        if case is None:
            case = ReturnCaseRecord(session_id=session_id)
            self.session.add(case)
            self.session.flush()
        return case

    def question(self, question_id: UUID) -> QuestionRequestRecord | None:
        return self.session.get(QuestionRequestRecord, question_id)

    def pending_question(self, session_id: UUID) -> QuestionRequestRecord | None:
        statement = (
            select(QuestionRequestRecord)
            .where(
                QuestionRequestRecord.session_id == session_id,
                QuestionRequestRecord.status == "pending",
            )
            .order_by(QuestionRequestRecord.created_at.desc())
        )
        return self.session.scalar(statement)

    def replace_pending_questions(self, session_id: UUID) -> None:
        pending = self.session.scalars(
            select(QuestionRequestRecord).where(
                QuestionRequestRecord.session_id == session_id,
                QuestionRequestRecord.status == "pending",
            )
        )
        for question in pending:
            question.status = "replaced"

    def expire_due_questions(self, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        due = list(
            self.session.scalars(
                select(QuestionRequestRecord).where(
                    QuestionRequestRecord.status == "pending",
                    QuestionRequestRecord.expires_at <= current,
                )
            )
        )
        for question in due:
            question.status = "expired"
        return len(due)

    def return_request_by_key(self, idempotency_key: str) -> ReturnRequestRecord | None:
        return self.session.scalar(
            select(ReturnRequestRecord).where(
                ReturnRequestRecord.idempotency_key == idempotency_key
            )
        )

    def return_request_for_case(self, case_id: UUID) -> ReturnRequestRecord | None:
        return self.session.scalar(
            select(ReturnRequestRecord).where(ReturnRequestRecord.return_case_id == case_id)
        )
