from collections.abc import Callable

from app.domain.models import ReturnCase, ReturnFacts


class FakeExtractor:
    def __init__(self, result: ReturnFacts | Callable[[str], ReturnFacts] | None = None) -> None:
        self.result = result or ReturnFacts()

    async def extract(
        self,
        message: str,
        current_case: ReturnCase,
        pending_question: str | None,
    ) -> ReturnFacts:
        del current_case, pending_question
        return self.result(message) if callable(self.result) else self.result
