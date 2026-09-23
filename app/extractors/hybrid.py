from app.domain.models import ReturnCase, ReturnFacts
from app.extractors.base import ExtractorError, FactExtractor
from app.extractors.rules import RuleBasedExtractor


class HybridExtractor:
    def __init__(self, fallback: FactExtractor | None = None) -> None:
        self.rules = RuleBasedExtractor()
        self.fallback = fallback

    async def extract(
        self,
        message: str,
        current_case: ReturnCase,
        pending_question: str | None,
    ) -> ReturnFacts:
        rule_facts = await self.rules.extract(message, current_case, pending_question)
        if self.fallback is None or self._answers_pending(rule_facts, pending_question):
            return rule_facts
        try:
            model_facts = await self.fallback.extract(message, current_case, pending_question)
        except ExtractorError:
            return rule_facts
        return self._merge(rule_facts, model_facts)

    @staticmethod
    def _answers_pending(facts: ReturnFacts, pending: str | None) -> bool:
        if pending is None:
            return (
                facts.order_id is not None and facts.reason is not None and facts.used is not None
            )
        if pending == "order_id":
            return facts.order_id is not None
        if pending == "reason":
            return facts.reason is not None
        if pending == "used":
            return facts.used is not None
        if pending == "opened":
            return facts.opened is not None
        return False

    @staticmethod
    def _merge(primary: ReturnFacts, secondary: ReturnFacts) -> ReturnFacts:
        first = primary.model_dump()
        second = secondary.model_dump()
        merged = {
            key: first[key] if first[key] is not None else second[key]
            for key in first
            if key != "wants_human"
        }
        merged["wants_human"] = primary.wants_human or secondary.wants_human
        if primary.intent == "unclear":
            merged["intent"] = secondary.intent
        return ReturnFacts.model_validate(merged)
