from typing import Protocol

from app.domain.models import ReturnCase, ReturnFacts


class FactExtractor(Protocol):
    async def extract(
        self,
        message: str,
        current_case: ReturnCase,
        pending_question: str | None,
    ) -> ReturnFacts: ...


class ExtractorError(Exception):
    """Raised when a provider cannot produce validated facts."""
