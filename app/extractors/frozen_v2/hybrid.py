from app.domain.models import ReturnCase, ReturnFacts
from app.extractors.base import ExtractorError, FactExtractor
from app.extractors.frozen_v2.rules import RuleBasedExtractor


class HybridExtractor:
    def __init__(self, fallback: FactExtractor | None = None) -> None:
        self.rules = RuleBasedExtractor()
        self.fallback = fallback
        self.last_path = "not_run"
        self.last_conflicts: list[str] = []

    async def extract(
        self,
        message: str,
        current_case: ReturnCase,
        pending_question: str | None,
    ) -> ReturnFacts:
        self.last_conflicts = []
        if self.fallback is not None:
            if hasattr(self.fallback, "last_usage"):
                self.fallback.last_usage = {}
            if hasattr(self.fallback, "last_diagnostics"):
                self.fallback.last_diagnostics = {}
        rule_facts = await self.rules.extract(message, current_case, pending_question)
        self.last_conflicts = list(getattr(self.rules, "ambiguous_fields", []))
        if self.fallback is None:
            self.last_path = "rules_only"
            return rule_facts
        complete_apparel = (
            current_case.item_category == "apparel"
            and pending_question is None
            and rule_facts.order_id is not None
            and rule_facts.reason is not None
            and all(
                getattr(rule_facts, field) is not None
                for field in ("stained", "tags_attached", "tags_intact", "damaged")
            )
        )
        if not self.last_conflicts and (
            complete_apparel or self._answers_pending(rule_facts, pending_question)
        ):
            self.last_path = "rules_sufficient"
            return rule_facts
        try:
            model_facts = await self.fallback.extract(message, current_case, pending_question)
        except ExtractorError:
            self.last_path = "model_error_rules_fallback"
            return rule_facts
        self.last_path = "rules_and_model"
        self.last_conflicts = sorted(
            set(self.last_conflicts)
            | {
                key
                for key in ReturnFacts.model_fields
                if key not in {"intent", "wants_human"}
                and getattr(rule_facts, key) is not None
                and getattr(model_facts, key) is not None
                and getattr(rule_facts, key) != getattr(model_facts, key)
            }
        )
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
        if pending in {"stained", "tags_attached", "tags_intact", "damaged", "condition_origin"}:
            return getattr(facts, pending) is not None
        return False

    @staticmethod
    def _merge(primary: ReturnFacts, secondary: ReturnFacts) -> ReturnFacts:
        first = primary.model_dump()
        second = secondary.model_dump()
        merged = {
            key: (
                None
                if first[key] is not None
                and second[key] is not None
                and first[key] != second[key]
                and key != "intent"
                else first[key]
                if first[key] is not None
                else second[key]
            )
            for key in first
            if key != "wants_human"
        }
        merged["wants_human"] = primary.wants_human or secondary.wants_human
        if primary.intent == "unclear":
            merged["intent"] = secondary.intent
        return ReturnFacts.model_validate(merged)
