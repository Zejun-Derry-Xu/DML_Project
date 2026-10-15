import re
from typing import Any

from app.domain.models import ReturnCase, ReturnFacts, ReturnReason

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
        # Unresolved subjects, speculation and prompt-like instructions must not
        # become confident rule facts. The model may clarify them, never approve.
        if re.search(
            r"\b(maybe|perhaps|probably|not sure|cannot tell|may have|not certain)\b", lowered
        ) or re.search(
            r"ignore (?:all |previous )?(?:rules|instructions)|output json|set \w+\s*="
            r"|one .*other|two .*which",
            lowered,
        ):
            safe_order = ORDER_PATTERN.search(text)
            return ReturnFacts(order_id=f"ORD-{safe_order.group(1)}" if safe_order else None)
        order_match = ORDER_PATTERN.search(text)
        order_id = f"ORD-{order_match.group(1)}" if order_match else None

        intent = "unclear"
        if any(term in lowered for term in ("return", "refund", "send back")):
            intent = "return"
        if any(term in lowered for term in ("cancel this return", "never mind", "nevermind")):
            intent = "not_return"

        item_text = re.sub(
            r"(?:the )?tags?[^.!;]*(?:damaged|torn|cut|removed|missing)[^.!;]*", "", lowered
        )
        reason = self._reason(item_text, pending_question)
        used = self._used(lowered, pending_question)
        positive_usage = re.sub(r"\b(?:never|not) used\b", "", lowered)
        if used is False and re.search(
            r"\b(?:i used|used it|used once|was used)\b", positive_usage
        ):
            self.ambiguous_fields.append("used")
            used = None
        opened = self._opened(lowered, pending_question)
        damaged = self._damaged(item_text)
        if damaged is False and re.search(
            r"\b(?:is damaged|arrived damaged|i damaged)\b", item_text
        ):
            self.ambiguous_fields.append("damaged")
            damaged = None
        if pending_question == "damaged" and lowered.strip(" .!?") in {"yes", "no", "yep", "nope"}:
            damaged = lowered.strip(" .!?") in {"yes", "yep"}
        condition = self._conditions(lowered, pending_question)
        if condition.get("condition_origin") == "customer" and reason == ReturnReason.DEFECTIVE:
            # Damage caused by the customer is a condition, not a manufactured defect claim.
            reason = None
            if "doesn't fit" in lowered or "does not fit" in lowered or "too small" in lowered:
                reason = ReturnReason.DOES_NOT_FIT
            elif "changed my mind" in lowered:
                reason = ReturnReason.CHANGED_MIND
        if pending_question is not None and pending_question != "reason":
            # A focused condition answer is not an opportunity to invent a new reason.
            reason = None
        wants_human = any(
            term in lowered
            for term in ("human", "a person", "real person", "support specialist", "agent")
        )

        item_name = self._item_name(text)
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

    def _conditions(self, text: str, pending: str | None) -> dict[str, Any]:
        patterns = {
            "stained": (
                r"\b(?:is stained|has stains|have stains|a stain|arrived stained|i stained)\b",
                r"\b(?:no stains|not stained|stain.free|is clean)\b",
            ),
            "tags_attached": (
                r"\btags? (?:are |is )?(?:still )?attached\b",
                r"\b(?:tags? (?:are |is |were |was )?(?:removed|missing)|cut off (?:the )?tags?"
                r"|tags? (?:are |is )?not attached)\b",
            ),
            "tags_intact": (
                r"\btags? (?:are |is )?(?:intact|undamaged)\b",
                r"\btags? (?:are |is )?(?:damaged|torn)\b",
            ),
        }
        values: dict[str, bool | str | None] = {}
        for field, (positive, negative) in patterns.items():
            pos, neg = bool(re.search(positive, text)), bool(re.search(negative, text))
            if pos and neg:
                self.ambiguous_fields.append(field)
                values[field] = None
            else:
                values[field] = True if pos else False if neg else None
            if pending == field and text.strip(" .!?") in {"yes", "yep", "no", "nope"}:
                values[field] = text.strip(" .!?") in {"yes", "yep"}
        origin = None
        if re.search(r"\bi (?:stained|damaged|cut off|removed|caused)\b", text):
            origin = "customer"
        if re.search(r"\b(?:arrived|delivered|delivery)\b", text) and any(
            value in text for value in ("stain", "damag", "missing", "removed", "torn")
        ):
            if origin:
                self.ambiguous_fields.append("condition_origin")
            origin = "pre_existing" if not origin else None
        if pending == "condition_origin":
            if text.strip(" .!?") in {"unknown", "i don't know", "i'm not sure"}:
                origin = "unknown"
            elif text.strip(" .!?") in {"i caused it", "customer"}:
                origin = "customer"
            elif text.strip(" .!?") in {"already present on delivery", "pre_existing"}:
                origin = "pre_existing"
        values["condition_origin"] = origin
        return values

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
    def _used(text: str, pending: str | None) -> bool | None:
        negative = (
            "never used",
            "not used",
            "unused",
            "did not use",
            "didn't use",
            "have not used",
        )
        if any(term in text for term in negative):
            return False
        if any(
            term in text for term in ("used it", "used once", "has been used", "was used", "i used")
        ):
            return True
        if pending == "used":
            if text.strip(" .!").casefold() in {"no", "nope"}:
                return False
            if text.strip(" .!").casefold() in {"yes", "yep", "yeah"}:
                return True
        return None

    @staticmethod
    def _opened(text: str, pending: str | None) -> bool | None:
        if any(term in text for term in ("unopened", "still sealed", "not opened")):
            return False
        if any(term in text for term in ("opened", "open the box")):
            return True
        if pending == "opened":
            if text.strip(" .!").casefold() in {"no", "nope"}:
                return False
            if text.strip(" .!").casefold() in {"yes", "yep", "yeah"}:
                return True
        return None

    @staticmethod
    def _damaged(text: str) -> bool | None:
        if any(term in text for term in ("not damaged", "isn't damaged")):
            return False
        if any(term in text for term in ("damaged", "broken", "faulty", "crack")):
            return True
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
