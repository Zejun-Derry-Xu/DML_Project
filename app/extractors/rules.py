import re

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
        order_match = ORDER_PATTERN.search(text)
        order_id = f"ORD-{order_match.group(1)}" if order_match else None

        intent = "unclear"
        if any(term in lowered for term in ("return", "refund", "send back")):
            intent = "return"
        if any(term in lowered for term in ("cancel this return", "never mind", "nevermind")):
            intent = "not_return"

        reason = self._reason(lowered, pending_question)
        used = self._used(lowered, pending_question)
        opened = self._opened(lowered, pending_question)
        damaged = self._damaged(lowered)
        wants_human = any(
            term in lowered
            for term in ("human", "a person", "real person", "support specialist", "agent")
        )

        item_name = self._item_name(text)
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
