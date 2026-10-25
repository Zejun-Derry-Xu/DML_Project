"""Small, deterministic collection planner; no additional model call or policy decision."""

from collections.abc import Mapping

COLLECTION_FIELDS = ("reason_text", "stained", "damaged", "tags_attached", "tags_intact")
DETAILS = {
    "reason_text": "why you would like to return it",
    "stained": "whether the clothing has any stains",
    "damaged": "whether the clothing itself has any damage",
    "tags_attached": "whether the original tags are still attached",
    "tags_intact": "whether the tags are intact and undamaged",
}


def collection_fields(anchor: str, states: Mapping[str, str], *, enabled: bool) -> list[str]:
    """Group only genuinely missing details. Conflicts need their own clarification."""
    if not enabled or anchor not in COLLECTION_FIELDS or states.get(anchor) == "conflict":
        return [anchor]
    return [field for field in COLLECTION_FIELDS if states.get(field, "missing") == "missing"]


def collection_prompt(fields: list[str], individual_prompt: str) -> str:
    if len(fields) <= 1:
        return individual_prompt
    remaining = set(fields)
    parts = []
    if "reason_text" in remaining:
        parts.append(DETAILS["reason_text"])
    if {"stained", "damaged"} <= remaining:
        parts.append("whether the clothing has any stains or damage")
    else:
        parts.extend(DETAILS[field] for field in ("stained", "damaged") if field in remaining)
    if {"tags_attached", "tags_intact"} <= remaining:
        parts.append("whether the original tags are still attached and undamaged")
    else:
        parts.extend(
            DETAILS[field] for field in ("tags_attached", "tags_intact") if field in remaining
        )
    details = "; ".join(parts)
    return (
        f"Please tell me {details}. "
        "A sentence or two is enough. It is okay to say you are not sure."
    )
