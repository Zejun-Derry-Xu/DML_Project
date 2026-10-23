"""Owned, durable apparel conversations. LLM understands; code controls transitions."""

import re
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.schemas import CaseResponse, PolicyCitation, QuestionResponse, ReturnRequestResponse
from app.config import Settings
from app.db.models import (
    CustomerRecord,
    MessageRecord,
    OrderItemRecord,
    OrderRecord,
    QuestionRequestRecord,
    ReturnCaseRecord,
    ReturnRequestRecord,
    SupportTicketRecord,
    ToolCallRecord,
)
from app.errors import AppError
from app.extractors.apparel_llm import BOOLEAN_FIELDS, Extraction, LLMFactExtractor, Observation
from app.extractors.base import ExtractorError
from app.policy.apparel import CONDITIONS, VERSION, load_apparel_policy, precheck
from app.repositories.order_repository import OrderRepository
from app.repositories.return_repository import ReturnRepository
from app.services.order_service import to_snapshot

WORKFLOW = "apparel-1"
TERMINAL = {"return_created", "closed", "escalated", "cancelled"}
PROMPTS = {
    "order_id": "Which order would you like to return?",
    "item_id": "Which item would you like to return?",
    "reason_text": "Why would you like to return this item? Please describe it in your own words.",
    "stained": "Does the clothing have any stains?",
    "damaged": "Is the clothing itself damaged (not its tags or packaging)?",
    "tags_attached": "Are the original tags still attached to the clothing?",
    "tags_intact": "Are the tags intact and undamaged?",
    "condition_origin": "Did you cause this condition, or was it present on delivery?",
    "confirm_return": "Please review the facts and policy below. Submit this simulated return?",
}


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class ApparelService:
    def __init__(self, db: Session, customer: CustomerRecord, settings: Settings) -> None:
        self.db, self.customer, self.settings = db, customer, settings
        self.returns = ReturnRepository(db)

    def owned(self, session_id: UUID) -> ReturnCaseRecord:
        case = self.returns.case_by_session(session_id)
        if case is None or not (
            case.customer_id == self.customer.id
            or (case.customer_id is None and case.customer_email == self.customer.email)
        ):
            raise AppError("CASE_NOT_FOUND", "This account has no such case.", 404)
        return case

    def _new_or_owned(self, session_id: UUID) -> ReturnCaseRecord:
        existing = self.returns.case_by_session(session_id)
        if existing:
            return self.owned(session_id)
        case = ReturnCaseRecord(
            session_id=session_id,
            customer_id=self.customer.id,
            customer_email=self.customer.email,
            workflow_version=WORKFLOW,
            policy_version=VERSION,
            field_observations={},
        )
        self.db.add(case)
        self.db.flush()
        return case

    def _order(self, number: str) -> OrderRecord:
        order = OrderRepository(self.db).by_number(number)
        if order is None or order.customer_id != self.customer.id:
            raise AppError("ORDER_NOT_FOUND", "This account has no such order.", 404)
        return order

    def list_orders(self) -> list[dict[str, Any]]:
        orders = self.db.scalars(
            select(OrderRecord)
            .where(OrderRecord.customer_id == self.customer.id)
            .order_by(OrderRecord.ordered_at.desc())
        ).all()
        policy = load_apparel_policy()
        return [
            {
                "order_number": o.order_number,
                "ordered_at": o.ordered_at.isoformat(),
                "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
                "items": [
                    {
                        "id": str(i.id),
                        "product_name": i.product_name,
                        "category": i.category,
                        "precheck": precheck(
                            to_snapshot(o),
                            next(s for s in to_snapshot(o).items if s.id == i.id),
                            policy,
                        ),
                    }
                    for i in o.items
                ],
            }
            for o in orders
        ]

    def _selected_item(self, case: ReturnCaseRecord) -> OrderItemRecord | None:
        if not case.order_number:
            return None
        order = self._order(case.order_number)
        return next((i for i in order.items if i.id == case.item_id), None)

    async def chat(self, session_id: UUID, message: str) -> CaseResponse:
        case = self._new_or_owned(session_id)
        if case.workflow_version != WORKFLOW or case.status in TERMINAL:
            return self.response(case)
        pending = self.returns.pending_question(session_id)
        message_id = uuid4()
        self.db.add(
            MessageRecord(id=message_id, session_id=session_id, role="user", content=message)
        )
        case.version += 1
        control = message.strip().casefold().rstrip(".!?")
        if control in {"cancel", "cancel return", "cancel this return"}:
            case.status = "cancelled"
            case.pending_question = None
            self.returns.replace_pending_questions(session_id)
            return self._finish(case)
        if control in {
            "human",
            "human support",
            "talk to a human",
            "can i talk to a human",
            "i want a human",
            "speak to a human",
            "human please",
        }:
            return self._ticket(case, "USER_REQUESTED_HUMAN")
        if not case.order_number:
            # Narrow optional shortcut; numeric answers are not guessed out of arbitrary text.
            numbers = re.findall(r"\bORD-[A-Za-z0-9]+\b", message, re.I)
            if len(set(n.upper() for n in numbers)) == 1:
                order = self._order(numbers[0])
                case.order_number, case.order_id = order.order_number, order.id
                if len(order.items) == 1:
                    case.item_id, case.item_name = order.items[0].id, order.items[0].product_name
            observations = dict(case.field_observations)
            observations["_intake"] = message
            observations["_intake_message_id"] = str(message_id)
            case.field_observations = observations
        if self._selected_item(case) is None:
            return self._advance(case)
        hard_result = self._precheck(case)
        if hard_result:
            return hard_result
        if pending and pending.field == "confirm_return" and control in {"yes", "confirm"}:
            # Natural text cannot silently submit an irreversible action.
            return self._advance(case)
        await self._extract(
            case,
            message,
            pending.field if pending and pending.field != "confirm_return" else None,
            message_id=str(message_id),
        )
        return self._advance(case)

    async def _extract(
        self,
        case: ReturnCaseRecord,
        message: str,
        pending: str | None,
        *,
        message_id: str | None = None,
    ) -> None:
        extractor = LLMFactExtractor(self.settings)
        started = perf_counter()
        observations = dict(case.field_observations)
        degraded = False
        try:
            result = await extractor.extract(
                message,
                {
                    "question": PROMPTS.get(pending or "", "Describe the return"),
                    "target": pending,
                    "selected_item": case.item_name,
                    "known_facts_reference_only": {
                        k: {"value": v.get("value"), "state": v.get("state")}
                        for k, v in observations.items()
                        if not k.startswith("_")
                    },
                },
            )
        except ExtractorError:
            degraded = True
            result = Extraction(intent="unclear", intent_evidence="", facts=[])
            # A direct answer to the reason question is a verbatim manual statement,
            # not a semantic fallback or a fabricated LLM extraction.
            if pending == "reason_text":
                result.facts.append(
                    Observation(
                        field="reason_text", value=message, state="stated", evidence=message
                    )
                )
        if result.intent == "human":
            observations["_human_requested"] = True
        if result.intent == "cancel":
            observations["_cancel_requested"] = True
        supplied = set()
        for fact in result.facts:
            if fact.state == "not_mentioned":
                continue
            supplied.add(fact.field)
            if fact.field in {"order_number", "item_name"}:
                current = case.order_number if fact.field == "order_number" else case.item_name
                if fact.value != current:
                    observations["_selection_changed"] = True
                continue
            previous = observations.get(fact.field, {})
            conflict = (
                previous.get("state") == "known"
                and fact.state == "stated"
                and previous.get("value") != fact.value
            )
            state = (
                "conflict"
                if conflict or fact.state == "conflict"
                else ("known" if fact.state == "stated" else "unknown")
            )
            if previous.get("state") == "known" and state == "unknown":
                continue
            entry = {
                "state": state,
                "value": previous.get("value") if conflict else fact.value,
                "candidate": fact.value if conflict else None,
                "evidence": fact.evidence,
                "message_id": message_id,
                "source": "manual" if degraded else "llm",
                "attempts": previous.get("attempts", 0)
                + int(pending == fact.field and state == "conflict"),
            }
            observations[fact.field] = entry
            if state == "known":
                self._set_value(case, fact.field, fact.value)
        if pending and pending not in supplied and pending != "confirm_return":
            old = observations.get(pending, {})
            attempts = old.get("attempts", 0) + 1
            observations[pending] = {
                **old,
                "attempts": attempts,
                "state": "unknown" if attempts >= 2 else "missing",
            }
        observations["_degraded"] = degraded
        case.field_observations = observations
        self.db.add(
            ToolCallRecord(
                session_id=case.session_id,
                tool_name="apparel_llm_extractor",
                arguments={"message_length": len(message), "pending_question": pending},
                result={
                    "model": self.settings.llm_model,
                    "degraded": degraded,
                    "rejected_fields": extractor.rejected_fields,
                    "usage": extractor.last_usage,
                },
                success=not degraded,
                latency_ms=round((perf_counter() - started) * 1000),
            )
        )

    @staticmethod
    def _set_value(case: ReturnCaseRecord, field: str, value: Any) -> None:
        if field == "reason_text":
            case.reason_text = value
        elif field in {*CONDITIONS, "used", "condition_origin"}:
            setattr(case, field, value)

    def _precheck(self, case: ReturnCaseRecord) -> CaseResponse | None:
        item = self._selected_item(case)
        if item is None or not case.order_number:
            return None
        order = to_snapshot(self._order(case.order_number))
        code = precheck(
            order,
            next(i for i in order.items if i.id == item.id),
            load_apparel_policy(case.policy_version),
        )
        if code == "NON_APPAREL":
            return self._ticket(case, code)
        if code:
            case.decision, case.decision_reason, case.status = "ineligible", code, "closed"
            self.returns.replace_pending_questions(case.session_id)
            case.pending_question = None
            return self._finish(case)
        return None

    def _advance(self, case: ReturnCaseRecord) -> CaseResponse:
        observations = case.field_observations
        if observations.get("_human_requested"):
            return self._ticket(case, "USER_REQUESTED_HUMAN")
        if observations.get("_cancel_requested"):
            case.status, case.pending_question = "cancelled", None
            self.returns.replace_pending_questions(case.session_id)
            return self._finish(case)
        if observations.get("_selection_changed"):
            return self._ticket(case, "UNRESOLVED_INFORMATION")
        if not case.order_number:
            options = [
                {
                    "value": o["order_number"],
                    "label": o["order_number"],
                    "description": "; ".join(
                        i["product_name"] + (f" · {i['precheck']}" if i["precheck"] else "")
                        for i in o["items"]
                    ),
                }
                for o in self.list_orders()
            ]
            if not options:
                return self._ticket(case, "NO_DEMO_ORDERS")
            return self._ask(case, "order_id", options)
        if self._selected_item(case) is None:
            options = [
                {
                    "value": str(i.id),
                    "label": i.product_name,
                    "description": "Support only" if i.category != "apparel" else None,
                }
                for i in self._order(case.order_number).items
            ]
            return self._ask(case, "item_id", options)
        hard_result = self._precheck(case)
        if hard_result:
            return hard_result
        policy = load_apparel_policy(case.policy_version)
        required = ["reason_text", *policy.required_conditions]
        adverse = any(
            observations.get(f, {}).get("state") == "known"
            and observations[f].get("value") != value
            for f, value in policy.required_conditions.items()
        )
        if adverse:
            required.append("condition_origin")
        for field in required:
            state = observations.get(field, {}).get("state", "missing")
            if state == "conflict":
                if observations[field].get("attempts", 0) < 1:
                    return self._ask(case, field)
                continue
            if state == "missing":
                return self._ask(case, field)
        if any(observations.get(f, {}).get("state") != "known" for f in required):
            return self._ticket(case, "UNRESOLVED_INFORMATION")
        if any(
            observations.get(f, {}).get("value") is True
            or observations.get(f, {}).get("state") in {"unknown", "conflict"}
            for f in ("reported_defect", "reported_wrong_item")
        ):
            return self._ticket(case, "CLAIM_REVIEW")
        if adverse:
            action = policy.origin_actions[str(case.condition_origin)]
            if action == "human_review":
                return self._ticket(case, "CONDITION_REVIEW")
            case.decision = "ineligible"
            case.decision_reason = "APPAREL_RESALE_CONDITION"
            case.status, case.pending_question = "closed", None
            self.returns.replace_pending_questions(case.session_id)
            return self._finish(case)
        case.decision, case.decision_reason = "eligible", "ELIGIBLE"
        return self._ask(case, "confirm_return")

    def _ask(
        self, case: ReturnCaseRecord, field: str, options: list[dict[str, Any]] | None = None
    ) -> CaseResponse:
        self.returns.replace_pending_questions(case.session_id)
        if options is None:
            if field == "confirm_return":
                options = [
                    {"value": "confirm", "label": "Confirm simulated return"},
                    {"value": "cancel", "label": "Cancel"},
                ]
            elif field == "condition_origin":
                options = [
                    {"value": "customer", "label": "I caused it"},
                    {"value": "pre_existing", "label": "Present on delivery"},
                    {"value": "unknown", "label": "I'm not sure"},
                ]
            elif field == "reason_text":
                options = [{"value": "unknown", "label": "I'm not sure"}]
            else:
                options = [
                    {"value": "yes", "label": "Yes"},
                    {"value": "no", "label": "No"},
                    {"value": "unknown", "label": "I'm not sure"},
                ]
        prompt = PROMPTS[field]
        if case.field_observations.get(field, {}).get("state") == "conflict":
            prompt = "Your statements differ. Please confirm: " + prompt
        question = QuestionRequestRecord(
            id=uuid4(),
            session_id=case.session_id,
            return_case_id=case.id,
            field=field,
            prompt=prompt,
            options=options,
            allow_free_text=field not in {"confirm_return", "order_id", "item_id"},
            status="pending",
            case_version=case.version,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        self.db.add(question)
        case.pending_question, case.status = field, "awaiting_user"
        case.decision = "eligible" if field == "confirm_return" else "need_more_information"
        case.decision_reason = "ELIGIBLE" if field == "confirm_return" else "MISSING_INFORMATION"
        return self._finish(case)

    async def answer(
        self, session_id: UUID, question_id: UUID, value: str | None, free_text: str | None
    ) -> CaseResponse:
        case = self.owned(session_id)
        if case.workflow_version != WORKFLOW:
            raise AppError(
                "READ_ONLY_WORKFLOW", "Historical cases are read-only. Start a new return.", 409
            )
        question = self.returns.question(question_id)
        if question is None or question.session_id != session_id:
            raise AppError("QUESTION_NOT_FOUND", "This case has no such question.", 404)
        if question.status == "answered" and case.status == "return_created":
            return self.response(case)
        if question.status != "pending" or question.case_version != case.version:
            raise AppError("STALE_ANSWER", "Refresh this case before answering.", 409)
        if aware(question.expires_at) <= datetime.now(UTC):
            raise AppError("QUESTION_EXPIRED", "Refresh this case before answering.", 410)
        if value is None and free_text and question.allow_free_text:
            return await self.chat(session_id, free_text)
        if value not in {o["value"] for o in question.options}:
            raise AppError("INVALID_ANSWER", "Choose one of this question's options.", 422)
        question.status, question.selected_value = "answered", value
        question.answered_at = datetime.now(UTC)
        self.db.add(MessageRecord(session_id=session_id, role="user", content=str(value)))
        case.version += 1
        if question.field == "confirm_return":
            if value == "cancel":
                case.status, case.pending_question = "cancelled", None
                return self._finish(case)
            return self._confirm(case, question)
        if question.field == "order_id":
            order = self._order(str(value))
            case.order_id, case.order_number = order.id, order.order_number
            if len(order.items) == 1:
                case.item_id, case.item_name = order.items[0].id, order.items[0].product_name
        elif question.field == "item_id":
            if not case.order_number:
                raise AppError("ORDER_REQUIRED", "Select an order first.", 409)
            item = next(
                (i for i in self._order(case.order_number).items if str(i.id) == value), None
            )
            if item is None:
                raise AppError("ITEM_NOT_FOUND", "Select an item from this order.", 404)
            case.item_id, case.item_name = item.id, item.product_name
        else:
            result: Any = (
                None
                if value == "unknown"
                else (value == "yes" if question.field in BOOLEAN_FIELDS else value)
            )
            observations = dict(case.field_observations)
            observations[question.field] = {
                "value": result,
                "state": "unknown" if value == "unknown" else "known",
                "source": "card",
                "question_id": str(question.id),
                "evidence": str(value),
                "attempts": 1,
            }
            case.field_observations = observations
            if result is not None:
                self._set_value(case, question.field, result)
        if question.field in {"order_id", "item_id"} and self._selected_item(case):
            hard = self._precheck(case)
            if hard:
                return hard
            intake = case.field_observations.get("_intake")
            if intake:
                obs = dict(case.field_observations)
                obs.pop("_intake", None)
                case.field_observations = obs
                await self._extract(case, intake, None, message_id=obs.get("_intake_message_id"))
        return self._advance(case)

    def _confirm(self, case: ReturnCaseRecord, question: QuestionRequestRecord) -> CaseResponse:
        hard = self._precheck(case)
        if hard:
            return hard
        # Recheck required facts, including current configuration, before the atomic claim.
        policy = load_apparel_policy(case.policy_version)
        obs = case.field_observations
        if (
            not case.reason_text
            or any(
                obs.get(f, {}).get("state") != "known" or obs[f].get("value") != expected
                for f, expected in policy.required_conditions.items()
            )
            or any(
                obs.get(f, {}).get("value")
                or obs.get(f, {}).get("state") in {"unknown", "conflict"}
                for f in ("reported_defect", "reported_wrong_item")
            )
        ):
            return self._ticket(case, "UNRESOLVED_INFORMATION")
        if case.decision != "eligible" or not case.item_id or not case.order_id:
            raise AppError("CONFIRMATION_REQUIRED", "Complete the current review first.", 409)
        claimed = self.db.execute(
            update(OrderItemRecord)
            .where(OrderItemRecord.id == case.item_id, OrderItemRecord.return_status.is_(None))
            .values(return_status="requested")
            .returning(OrderItemRecord.id)
        ).scalar_one_or_none()
        if claimed is None:
            raise AppError("ORDER_ALREADY_RETURNED", "This item already has a return.", 409)
        self.db.add(
            ReturnRequestRecord(
                id=uuid4(),
                rma_number=f"RMA-{uuid4().hex[:12].upper()}",
                return_case_id=case.id,
                order_id=case.order_id,
                item_id=case.item_id,
                idempotency_key=str(question.id),
                status="requested",
            )
        )
        case.status, case.pending_question = "return_created", None
        self.returns.replace_pending_questions(case.session_id)
        return self._finish(case)

    def _ticket(self, case: ReturnCaseRecord, reason: str) -> CaseResponse:
        existing = self.db.scalar(
            select(SupportTicketRecord).where(SupportTicketRecord.return_case_id == case.id)
        )
        if existing is None:
            self.db.add(
                SupportTicketRecord(
                    return_case_id=case.id,
                    customer_id=self.customer.id,
                    status="open",
                    snapshot={
                        "session_id": str(case.session_id),
                        "order_number": case.order_number,
                        "item_name": case.item_name,
                        "reason_text": case.reason_text,
                        "intake": case.field_observations.get("_intake"),
                        "observations": case.field_observations,
                        "review_reason": reason,
                        "policy_version": case.policy_version,
                        "workflow_version": WORKFLOW,
                    },
                )
            )
        case.status, case.decision, case.decision_reason = "escalated", "human_review", reason
        case.pending_question = None
        self.returns.replace_pending_questions(case.session_id)
        return self._finish(case)

    def resume(self, session_id: UUID) -> CaseResponse:
        case = self.owned(session_id)
        if case.workflow_version != WORKFLOW or case.status in TERMINAL:
            return self.response(case)
        pending = self.returns.pending_question(session_id)
        if pending and aware(pending.expires_at) > datetime.now(UTC):
            return self.response(case)
        case.version += 1
        return self._advance(case)

    def _finish(self, case: ReturnCaseRecord) -> CaseResponse:
        self.db.flush()
        response = self.response(case)
        self.db.add(
            MessageRecord(session_id=case.session_id, role="assistant", content=response.reply)
        )
        self.db.commit()
        return response

    def response(self, case: ReturnCaseRecord) -> CaseResponse:
        readonly = case.workflow_version != WORKFLOW
        pending = self.returns.pending_question(case.session_id) if not readonly else None
        ticket = self.db.scalar(
            select(SupportTicketRecord).where(SupportTicketRecord.return_case_id == case.id)
        )
        request = self.db.scalar(
            select(ReturnRequestRecord).where(ReturnRequestRecord.return_case_id == case.id)
        )
        replies = {
            "closed": f"Not eligible: {case.decision_reason}.",
            "return_created": "Your simulated return request has been created.",
            "cancelled": "The return was cancelled.",
            "escalated": "A simulated support ticket is recorded. No external agent was notified.",
        }
        reply = (
            "This historical case is read-only. Start a new return to use the apparel workflow."
            if readonly
            else pending.prompt
            if pending
            else replies.get(case.status, "Return review")
        )
        citations = []
        if readonly:
            from app.policy.corpus import load_policy

            try:
                corpus = load_policy(case.policy_version)
            except (OSError, ValueError):
                corpus = None
        else:
            corpus = load_apparel_policy(case.policy_version).corpus()
        if corpus:
            clauses = [c for c in corpus.clauses if case.decision_reason in c.reason_codes]
            citations = [
                PolicyCitation(
                    clause_id=c.id, policy_version=corpus.version, scope=c.scope, content=c.content
                )
                for c in clauses
            ]
        return CaseResponse(
            session_id=case.session_id,
            state=case.status,
            decision=case.decision,
            reason_code=case.decision_reason,
            reply=reply,
            question=QuestionResponse(
                question_id=pending.id,
                field=pending.field,
                prompt=pending.prompt,
                options=pending.options,
                allow_free_text=pending.allow_free_text,
                status=pending.status,
                expires_at=pending.expires_at,
            )
            if pending
            else None,
            return_request=ReturnRequestResponse(
                id=request.id,
                rma_number=request.rma_number,
                status=request.status,
                created_at=request.created_at,
            )
            if request
            else None,
            workflow_version=case.workflow_version,
            read_only=readonly,
            policy_version=case.policy_version,
            policy_evidence=citations,
            degraded=bool(case.field_observations.get("_degraded", False)),
            facts={
                "reason_text": case.reason_text,
                "item_name": case.item_name,
                "order_number": case.order_number,
                **{
                    k: v
                    for k, v in case.field_observations.items()
                    if not k.startswith("_") and k != "reason_text"
                },
            },
            support_ticket={
                "id": str(ticket.id),
                "status": ticket.status,
                "notice": "Simulated; no external notification",
            }
            if ticket
            else None,
        )
