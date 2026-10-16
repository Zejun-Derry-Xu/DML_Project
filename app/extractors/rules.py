import re

from app.domain.models import ReturnCase, ReturnFacts, ReturnReason
from app.extractors.products import product_span
from app.extractors.scoped import order_identifier, scoped_conditions

ORDER_PATTERN = re.compile(r"\bORD[-\s]?(\d{4,})\b", re.IGNORECASE)


class RuleBasedExtractor:
    async def extract(
        self,
        message: str,
        current_case: ReturnCase,
        pending_question: str | None,
    ) -> ReturnFacts:
        text = message.strip()
        lowered = text.casefold()
        self.ambiguous_fields: list[str] = []
        scoped = scoped_conditions(message, current_case, pending_question)
        self.last_diagnostics = {
            "field_states": scoped.states,
            "evidence_spans": {
                field: [message.find(quote), message.find(quote) + len(quote)]
                for field, quote in scoped.evidence.items()
            },
            "blocked_scope": scoped.blocked,
        }
        self.last_trace = {"rule_evidence": scoped.evidence}
        topics = {
            "stained": r"stain|clean|spot",
            "tags_attached": r"attach|fasten|remov|missing|detach|taken off|absent|tags? .* on",
            "tags_intact": r"tags?[^.;!?]*(?:intact|damage|torn|tear|rip|broken)",
            "damaged": r"(?:shirt|garment|fabric|sleeve)[^.;!?]*(?:damage|rip|tear|hole)",
            "condition_origin": r"caus|arriv|deliver|fault|responsib",
        }
        self.unresolved_fields = [
            field
            for field, pattern in topics.items()
            if scoped.values.get(field) is None and re.search(pattern, lowered)
        ]
        self.ambiguous_fields = list(scoped.conflicts)
        order_id, order_conflict, _ = order_identifier(text, pending_question)
        if order_conflict:
            self.ambiguous_fields.append("order_id")
        if scoped.blocked:
            return ReturnFacts(
                order_id=order_id,
                wants_human=bool(
                    re.search(r"\b(?:speak|talk|want|need).*(?:human|agent|person)\b", lowered)
                ),
            )
        # Unresolved subjects, speculation and prompt-like instructions must not
        # become confident rule facts. The model may clarify them, never approve.
        intent = "unclear"
        if any(term in lowered for term in ("return", "refund", "send back")):
            intent = "return"
        if any(term in lowered for term in ("cancel this return", "never mind", "nevermind")):
            intent = "not_return"

        item_text = re.sub(
            r"(?:the )?tags?[^.!;]*(?:damaged|torn|cut|removed|missing)[^.!;]*", "", lowered
        )
        reason = self._reason(item_text, pending_question)
        used = scoped.values.get("used")
        positive_usage = re.sub(r"\b(?:never|not) used\b", "", lowered)
        if used is False and re.search(
            r"\b(?:i used|used it|used once|was used)\b", positive_usage
        ):
            self.ambiguous_fields.append("used")
            used = None
        opened = scoped.values.get("opened")
        damaged = scoped.values.get("damaged")
        if damaged is False and re.search(
            r"\b(?:is damaged|arrived damaged|i damaged)\b", item_text
        ):
            self.ambiguous_fields.append("damaged")
            damaged = None
        if pending_question == "damaged" and lowered.strip(" .!?") in {"yes", "no", "yep", "nope"}:
            damaged = lowered.strip(" .!?") in {"yes", "yep"}
        condition = {
            field: scoped.values.get(field)
            for field in ("stained", "tags_attached", "tags_intact", "condition_origin")
        }
        if (
            current_case.item_category == "apparel"
            and reason == ReturnReason.DEFECTIVE
            and not any(term in lowered for term in ("defective", "faulty", "does not work"))
        ):
            reason = None
        if condition.get("condition_origin") == "customer" and reason == ReturnReason.DEFECTIVE:
            # Damage caused by the customer is a condition, not a manufactured defect claim.
            reason = None
            if "doesn't fit" in lowered or "does not fit" in lowered or "too small" in lowered:
                reason = ReturnReason.DOES_NOT_FIT
            elif "changed my mind" in lowered:
                reason = ReturnReason.CHANGED_MIND
        # Plain condition damage is not automatically a new defect claim.
        # Explicit wrong-item/fit/change-of-mind corrections still reach state merging.
        if (
            pending_question not in {None, "reason"}
            and reason == ReturnReason.DEFECTIVE
            and not any(term in lowered for term in ("defective", "faulty", "does not work"))
        ):
            reason = None
        wants_human = any(
            term in lowered
            for term in ("human", "a person", "real person", "support specialist", "agent")
        )

        item_name = product_span(text) or self._item_name(text)
        if item_name and any(
            term in item_name.casefold() for term in ("order number", "phone number", "order id")
        ):
            item_name = None
        if item_name and item_name.casefold() in {"name", "username", "account", "order"}:
            item_name = None
        if current_case.item_category == "apparel" and pending_question in {
            "used",
            "opened",
            "stained",
            "tags_attached",
            "tags_intact",
            "damaged",
            "condition_origin",
        }:
            item_name = None
        if pending_question == "item_id" and item_name is None and len(text) <= 100:
            item_name = text.strip(" .!?")

        return ReturnFacts(
            intent=intent,
            order_id=order_id,
            item_name=item_name,
            reason=reason,
            used=used,
            opened=opened,
            damaged=damaged,
            wants_human=wants_human,
            **condition,
        )

    @staticmethod
    def _reason(text: str, pending: str | None) -> ReturnReason | None:
        if any(term in text for term in ("wrong item", "something else")):
            return ReturnReason.WRONG_ITEM
        if any(
            term in text
            for term in ("defective", "damaged", "broken", "faulty", "does not work", "crack")
        ) and not any(term in text for term in ("not damaged", "isn't damaged")):
            return ReturnReason.DEFECTIVE
        if any(term in text for term in ("doesn't fit", "does not fit", "too small", "too large")):
            return ReturnReason.DOES_NOT_FIT
        if any(
            term in text
            for term in ("changed my mind", "no longer want", "no longer wanted", "unwanted")
        ):
            return ReturnReason.CHANGED_MIND
        if pending == "reason" and any(term in text for term in ("other", "another reason")):
            return ReturnReason.OTHER
        return None

    @staticmethod
    def _item_name(text: str) -> str | None:
        patterns = (
            r"(?:return|refund|send back)\s+(?:the\s+|my\s+)?(.+?)"
            r"(?:\s+from\s+(?:order\s+)?ORD[-\s]?\d+|\s+on\s+ORD[-\s]?\d+|[.!?]|$)",
            r"(?:the|my)\s+([A-Za-z][A-Za-z\- ]{1,50}?)\s+"
            r"(?:is|are|was|were|doesn't|does not|from)",
            r"no longer want(?:ed)?\s+(?:the\s+)?([A-Za-z][A-Za-z\- ]{1,50}?)[.!?]?$",
            r"(?:my\s+)?ORD[-\s]?\d+\s+([A-Za-z][A-Za-z\-]*)(?:\s+is|\s+was|\s+doesn't)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
                if candidate.casefold() not in {"item", "order", "this"}:
                    return candidate
        return None
