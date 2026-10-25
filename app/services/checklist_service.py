"""Snapshot-bound customer attestations. Language understanding never authorizes a scope."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.api.schemas import CaseResponse, ChecklistItemResponse, PolicyCitation
from app.db.models import MessageRecord, QuestionRequestRecord, ReturnCaseRecord
from app.errors import AppError
from app.policy.apparel import CONDITIONS, load_apparel_policy
from app.policy.retrieval import LexicalPolicyRetriever
from app.services.apparel_service import TERMINAL, WORKFLOW, ApparelService, aware

# Text names the UNWANTED condition. "None apply" has an unambiguous, recorded scope.
PROBLEMS = {
    "stained": ("Stains on the clothing", "No stains on the clothing"),
    "damaged": ("Damage to the clothing itself", "No damage to the clothing itself"),
    "tags_attached": ("Original tags still attached", "Original tags cut off, removed or detached"),
    "tags_intact": ("Undamaged tags", "Damaged tags"),
}


class ChecklistService(ApparelService):
    def _valid_question(self, case: ReturnCaseRecord, question: QuestionRequestRecord) -> None:
        if question.status != "pending" or question.case_version != case.version:
            raise AppError("STALE_ANSWER", "Refresh this case before answering.", 409)
        if aware(question.expires_at) <= datetime.now(UTC):
            raise AppError("QUESTION_EXPIRED", "Refresh this case before answering.", 410)

    def _bound(self, case: ReturnCaseRecord, question: QuestionRequestRecord) -> bool:
        snapshot = case.field_observations.get("_checklist", {})
        return bool(
            question.field == "condition_checklist"
            and snapshot.get("question_id") == str(question.id)
            and snapshot.get("case_version") == question.case_version
            and snapshot.get("item_id") == str(case.item_id)
            and snapshot.get("order_number") == case.order_number
            and snapshot.get("policy_version") == case.policy_version
            and snapshot.get("expected")
            == load_apparel_policy(case.policy_version).required_conditions
        )

    def _attest(
        self,
        case: ReturnCaseRecord,
        question: QuestionRequestRecord,
        evidence: str,
        message_id: str | None,
    ) -> bool:
        if not self._bound(case, question):
            return False
        observations = dict(case.field_observations)
        expected = load_apparel_policy(case.policy_version).required_conditions
        if observations.get("_selection_changed") or any(
            observations.get(f, {}).get("state") == "conflict"
            or (
                observations.get(f, {}).get("state") == "known"
                and observations[f].get("value") != value
            )
            for f, value in expected.items()
        ):
            observations["_attestation_blocked"] = True
            case.field_observations = observations
            return False
        attestation = {
            "question_id": str(question.id),
            "snapshot": observations["_checklist"],
            "evidence": evidence,
            "message_id": message_id,
        }
        history = list(observations.get("_attestations", []))
        history.append(attestation)
        observations["_attestations"] = history
        for field, value in expected.items():
            previous = observations.get(field)
            observations[field] = {
                "value": value,
                "state": "known",
                "source": "user_attestation",
                "evidence": evidence,
                "message_id": message_id,
                "question_id": str(question.id),
                "previous": previous,
            }
            self._set_value(case, field, value)
        observations["_locating_uncertainty"] = False
        observations["_clarification_attempts"] = 0
        case.field_observations = observations
        return True

    def _policy_reply(self, case: ReturnCaseRecord, query: str, topics: list[str]) -> None:
        corpus = load_apparel_policy(case.policy_version).corpus()
        canonical = (
            "deadline delivery days"
            if topics == ["window"]
            else ("tags stains damage origin cause arrived" if topics else query)
        )
        clauses = LexicalPolicyRetriever(corpus).search(canonical, scope="eligibility", limit=3)
        ids = [c.id for c in clauses]
        if "tag_cleanliness" in topics:
            lead = (
                "This policy does not specify a separate cleanliness rule for tags. "
                "I cannot invent a rejection rule for that; simulated support can review it."
            )
        elif topics and topics != ["window"]:
            lead = (
                "I found the condition and origin rules below. When a condition is not met, "
                "I need to know whether it was present on delivery or happened later. "
                "I will not guess who caused it."
            )
        else:
            lead = (
                "Here is the relevant policy."
                if clauses
                else (
                    "I could not find a clause answering that question; "
                    "I cannot invent an exception."
                )
            )
        text = lead + "\n" + "\n".join(f"[{c.id}] {c.content}" for c in clauses)
        case.field_observations = {
            **case.field_observations,
            "_policy_text": text.strip(),
            "_policy_ids": ids,
        }

    async def chat(
        self,
        session_id: UUID,
        message: str,
        in_reply_to_question_id: UUID | None = None,
    ) -> CaseResponse:
        case = self._new_or_owned(session_id)
        if case.workflow_version != WORKFLOW or case.status in TERMINAL:
            return self.response(case)
        control = message.strip().casefold().rstrip(".!?")
        if self._selected_item(case) is None or control in {
            "cancel",
            "cancel return",
            "cancel this return",
            "human",
            "human support",
            "talk to a human",
            "can i talk to a human",
            "i want a human",
            "speak to a human",
            "human please",
        }:
            return await super().chat(session_id, message, in_reply_to_question_id)
        pending = self.returns.pending_question(session_id)
        if in_reply_to_question_id is not None:
            if not pending or pending.id != in_reply_to_question_id:
                raise AppError(
                    "STALE_ANSWER", "Reply to the current question after refreshing.", 409
                )
            self._valid_question(case, pending)
        bound = bool(
            pending and in_reply_to_question_id == pending.id and self._bound(case, pending)
        )
        hard = self._precheck(case)
        if hard:
            return hard
        before = {
            f: (
                case.field_observations.get(f, {}).get("state"),
                case.field_observations.get(f, {}).get("value"),
            )
            for f in CONDITIONS
        }
        case.field_observations = {
            k: v
            for k, v in case.field_observations.items()
            if k not in {"_policy_text", "_policy_ids", "_attestation_blocked"}
        }
        message_id = uuid4()
        self.db.add(
            MessageRecord(id=message_id, session_id=session_id, role="user", content=message)
        )
        result = await self._extract(
            case,
            message,
            pending.field if pending else None,
            message_id=str(message_id),
        )
        reply = result.checklist_reply
        if reply.policy_question:
            self._policy_reply(case, reply.policy_question, list(reply.topics))
        has_facts = any(f.state != "not_mentioned" for f in result.facts)
        # A policy-only detour does not replace/invalidate the pending consent snapshot.
        if (
            reply.policy_question
            and not has_facts
            and reply.kind in {"none", "uncertain"}
            and not reply.submit_requested
        ):
            return self._finish(case)
        if case.field_observations.get("_degraded"):
            return self._finish(case) if pending else self._advance(case)
        consent = False
        adverse_in_message = any(
            f.field in CONDITIONS
            and (
                f.state in {"uncertain", "conflict"}
                or f.state == "stated"
                and f.value != load_apparel_policy(case.policy_version).required_conditions[f.field]
            )
            for f in result.facts
        )
        if reply.kind == "all_clear" and bound and pending and not adverse_in_message:
            consent = self._attest(case, pending, reply.evidence, str(message_id))
        if reply.kind == "all_clear" and not bound:
            case.field_observations = {**case.field_observations, "_needs_current_checklist": True}
        if reply.kind == "exception" and "tag_cleanliness" in reply.topics:
            if not reply.policy_question:
                self._policy_reply(case, reply.evidence, list(reply.topics))
            case.version += 1
            return self._ticket(case, "POLICY_UNSPECIFIED")
        progress = any(
            before[f]
            != (
                case.field_observations.get(f, {}).get("state"),
                case.field_observations.get(f, {}).get("value"),
            )
            for f in CONDITIONS
        )
        if not progress and reply.kind != "all_clear":
            old = case.field_observations
            attempts = int(old.get("_clarification_attempts", 0)) + int(
                bool(old.get("_locating_uncertainty"))
                or bool(pending and pending.field in {*CONDITIONS, "condition_origin"})
            )
            case.field_observations = {
                **old,
                "_locating_uncertainty": True,
                "_clarification_attempts": attempts,
            }
        elif progress:
            case.field_observations = {
                **case.field_observations,
                "_locating_uncertainty": False,
                "_clarification_attempts": 0,
            }
        if pending and reply.submit_requested and in_reply_to_question_id == pending.id:
            self._valid_question(case, pending)
        case.version += 1
        if (
            pending
            and reply.submit_requested
            and (
                consent
                or pending.field == "confirm_return"
                and in_reply_to_question_id == pending.id
            )
        ):
            # Same atomic claim and rechecks as the existing explicit confirmation path.
            pending.status, pending.selected_value = (
                "answered",
                "attest_and_submit" if consent else "confirm",
            )
            pending.answered_at = datetime.now(UTC)
            case.field_observations = {
                **case.field_observations,
                "_submission": {
                    "question_id": str(pending.id),
                    "evidence": reply.submit_evidence,
                    "message_id": str(message_id),
                },
            }
            case.decision = "eligible"
            return self._confirm(case, pending)
        return self._advance(case)

    def _ask_checklist(self, case: ReturnCaseRecord) -> CaseResponse:
        self.returns.replace_pending_questions(case.session_id)
        policy = load_apparel_policy(case.policy_version)
        question_id = uuid4()
        items = [
            {"field": f, "problem": PROBLEMS[f][int(v)], "expected_value": v}
            for f, v in policy.required_conditions.items()
        ]
        prompt = (
            f"Your order and return-window checks passed for "
            f"{case.item_name} ({case.order_number}). "
            "Review the conditions listed below together. "
            "You can confirm together or tell me only the exceptions or uncertain details. "
            "Say 'None of these problems apply, and submit my return' to create a simulated return "
            "request in one step. This does not transfer money. A return reason is optional."
        )
        if case.field_observations.get("_locating_uncertainty"):
            prompt = (
                "Which condition is uncertain or not met? Tell me the exceptions together; "
                "you do not need to repeat what is already known."
            )
        if case.field_observations.get("_attestation_blocked"):
            prompt = (
                "You previously reported an exception. A collective confirmation cannot replace "
                "that fact. Please clarify that specific condition."
            )
        question = QuestionRequestRecord(
            id=question_id,
            session_id=case.session_id,
            return_case_id=case.id,
            field="condition_checklist",
            prompt=prompt,
            options=[
                {
                    "value": "attest_and_submit",
                    "label": "I confirm none of these problems apply "
                    "and submit this simulated return",
                },
                {"value": "uncertain", "label": "I have an exception or I am not sure"},
                {"value": "cancel", "label": "Cancel return"},
            ],
            allow_free_text=True,
            status="pending",
            case_version=case.version,
            expires_at=datetime.now(UTC) + timedelta(minutes=self.settings.question_ttl_minutes),
        )
        self.db.add(question)
        case.field_observations = {
            **case.field_observations,
            "_checklist": {
                "question_id": str(question_id),
                "case_version": case.version,
                "order_number": case.order_number,
                "item_id": str(case.item_id),
                "policy_version": case.policy_version,
                "expected": policy.required_conditions,
                "items": items,
                "prompt": prompt,
            },
        }
        case.pending_question, case.status = "condition_checklist", "awaiting_user"
        case.decision, case.decision_reason = "need_more_information", "MISSING_INFORMATION"
        return self._finish(case)

    def _advance(self, case: ReturnCaseRecord) -> CaseResponse:
        obs = case.field_observations
        if (
            not case.order_number
            or not self._selected_item(case)
            or any(
                obs.get(f) for f in ("_human_requested", "_cancel_requested", "_selection_changed")
            )
        ):
            return super()._advance(case)
        hard = self._precheck(case)
        if hard:
            return hard
        policy = load_apparel_policy(case.policy_version)
        if any(
            obs.get(f, {}).get("value") is True
            or obs.get(f, {}).get("state") in {"unknown", "conflict"}
            for f in ("reported_defect", "reported_wrong_item")
        ):
            return self._ticket(case, "CLAIM_REVIEW")
        if int(obs.get("_clarification_attempts", 0)) >= 2:
            return self._ticket(case, "UNRESOLVED_INFORMATION")
        for field in CONDITIONS:
            if obs.get(field, {}).get("state") == "conflict":
                if obs[field].get("attempts", 0) >= 1:
                    return self._ticket(case, "UNRESOLVED_INFORMATION")
                return self._ask(case, field)
        adverse = any(
            obs.get(f, {}).get("state") == "known" and obs[f].get("value") != value
            for f, value in policy.required_conditions.items()
        )
        if adverse:
            if "_policy_text" not in obs:
                self._policy_reply(case, "tags stains damage origin", ["condition", "origin"])
            origin = obs.get("condition_origin", {})
            if origin.get("state") == "known":
                if policy.origin_actions[str(origin["value"])] == "human_review":
                    return self._ticket(case, "CONDITION_REVIEW")
                case.status, case.decision, case.decision_reason = (
                    "closed",
                    "ineligible",
                    "APPAREL_RESALE_CONDITION",
                )
                case.pending_question = None
                self.returns.replace_pending_questions(case.session_id)
                return self._finish(case)
            if origin.get("state") in {"unknown", "conflict"}:
                return self._ticket(case, "UNRESOLVED_INFORMATION")
            return self._ask(case, "condition_origin")
        if obs.get("_locating_uncertainty") or obs.get("_attestation_blocked"):
            return self._ask_checklist(case)
        states = [obs.get(f, {}).get("state", "missing") for f in CONDITIONS]
        if "missing" in states:
            return self._ask_checklist(case)
        if any(state != "known" for state in states):
            return self._ticket(case, "UNRESOLVED_INFORMATION")
        case.decision, case.decision_reason = "eligible", "ELIGIBLE"
        return self._ask(case, "confirm_return")

    async def answer(
        self,
        session_id: UUID,
        question_id: UUID,
        value: str | None,
        free_text: str | None,
    ) -> CaseResponse:
        case = self.owned(session_id)
        question = self.returns.question(question_id)
        if not question or question.session_id != session_id:
            raise AppError("QUESTION_NOT_FOUND", "This case has no such question.", 404)
        if question.field != "condition_checklist":
            return await super().answer(session_id, question_id, value, free_text)
        if case.status == "return_created" and question.selected_value == "attest_and_submit":
            return self.response(case)
        self._valid_question(case, question)
        if free_text and value is None:
            return await self.chat(session_id, free_text, question_id)
        if value not in {o["value"] for o in question.options}:
            raise AppError("INVALID_ANSWER", "Use an option on this checklist.", 422)
        if not self._bound(case, question):
            raise AppError("STALE_ANSWER", "Review the current checklist.", 409)
        self.db.add(MessageRecord(session_id=session_id, role="user", content=str(value)))
        case.version += 1
        if value == "cancel":
            case.status, case.pending_question = "cancelled", None
            self.returns.replace_pending_questions(session_id)
            return self._finish(case)
        if value == "uncertain":
            obs = case.field_observations
            case.field_observations = {
                **obs,
                "_locating_uncertainty": True,
                "_clarification_attempts": int(obs.get("_clarification_attempts", 0))
                + int(bool(obs.get("_locating_uncertainty"))),
            }
            return self._advance(case)
        if not self._attest(case, question, str(question.options[0]["label"]), None):
            return self._advance(case)
        question.status, question.selected_value = "answered", "attest_and_submit"
        question.answered_at = datetime.now(UTC)
        case.decision = "eligible"
        return self._confirm(case, question)

    def resume(self, session_id: UUID) -> CaseResponse:
        case = self.owned(session_id)
        pending = self.returns.pending_question(session_id)
        if (
            case.workflow_version == WORKFLOW
            and case.status not in TERMINAL
            and pending
            and (
                pending.field in {*CONDITIONS, "reason_text"}
                and not case.field_observations.get("_checklist")
            )
        ):
            case.version += 1
            return self._advance(case)
        return super().resume(session_id)

    def response(self, case: ReturnCaseRecord) -> CaseResponse:
        response = super().response(case)
        if response.read_only:
            return response
        snapshot = case.field_observations.get("_checklist", {})
        if response.question and snapshot.get("question_id") == str(response.question.question_id):
            response.question.checklist_items = [
                ChecklistItemResponse(**i) for i in snapshot["items"]
            ]
            response.question.requested_fields = list(snapshot["expected"])
        text = case.field_observations.get("_policy_text")
        if text:
            response.reply = str(text) + "\n\n" + response.reply
            existing = {c.clause_id for c in response.policy_evidence}
            corpus = load_apparel_policy(case.policy_version).corpus()
            response.policy_evidence.extend(
                PolicyCitation(
                    clause_id=c.id,
                    policy_version=case.policy_version,
                    scope=c.scope,
                    content=c.content,
                )
                for c in corpus.clauses
                if c.id in case.field_observations.get("_policy_ids", []) and c.id not in existing
            )
        return response
