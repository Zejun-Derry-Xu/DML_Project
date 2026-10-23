"""Source IDs select exact character spans; no fuzzy or model-rewritten evidence."""

import re
from typing import TypedDict


class Source(TypedDict):
    id: str
    text: str
    start: int
    end: int


def sources(message: str) -> list[Source]:
    result: list[Source] = []
    for match in re.finditer(r"[^.;!?\n]+", message):
        text = match.group()
        start = match.start() + len(text) - len(text.lstrip())
        quote = text.strip()
        if quote:
            result.append(
                {"id": f"E{len(result)}", "text": quote, "start": start, "end": start + len(quote)}
            )
    return result


def resolve(reference: str, message: str) -> Source | None:
    return next((source for source in sources(message) if source["id"] == reference), None)
