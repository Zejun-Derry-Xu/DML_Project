"""Conservative assertion scope and shared identifier parsing, with source evidence."""

import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import ReturnCase

PREFIXED_ORDER = re.compile(r"\bORD[-\s]?(\d{4,})(?!\w|[-/]\d)", re.I)
INJECTION = re.compile(
    r"ignore (?:all |previous )?(?:rules|instructions)|output json|set \w+\s*=|"
    r"regardless of (?:the facts|what i)",
    re.I,
)
UNRESOLVED_SUBJECT = re.compile(
    r"\b(?:different (?:shirt|item|garment)|other (?:shirt|item|garment)|"
    r"one .*other|two .*which|not (?:this|the selected) (?:one|shirt|item))\b",
    re.I,
)
UNCERTAIN = re.compile(
    r"\b(?:not sure|cannot (?:tell|confirm|establish)|can't (?:tell|confirm)|"
    r"don't know|do not know|not certain|maybe|perhaps|probably|may have|might|"
    r"not (?:checked|verified)|nobody has verified|before i can answer|"
    r"no reliable information)\b",
    re.I,
)
HYPOTHETICAL = re.compile(r"\b(?:if|suppose|hypothetically|would|wondered|whether)\b", re.I)
COMPLEX_NEGATION = re.compile(r"\bnot\s+not\b|\bno\s+(?:lack|absence)\b", re.I)
BOOL_FIELDS = ("stained", "damaged", "tags_attached", "tags_intact", "used", "opened")


def order_identifier(message: str, pending: str | None = None) -> tuple[str | None, bool, str]:
    """No artificial ORD prefix on native numeric IDs; ambiguity never picks the first."""
    matches = [(f"ORD-{m.group(1)}", m.group()) for m in PREFIXED_ORDER.finditer(message)]
    for m in re.finditer(
        r"\border\s*(?:number|id|#)?\s*[,#:=]?\s*"
        r"(?:(?:which|it)\s+)?(?:is|was)?\s*[:=#]?\s*(\d{4,20})(?!\w|[-/]\d|\.\d)",
        message,
        re.I,
    ):
        matches.append((m.group(1), m.group()))
        for alternate in re.finditer(r"\s*(?:or|and|,)\s*(\d{4,20})(?!\d)", message[m.end() :]):
            if alternate.start() > 0:
                break
            matches.append((alternate.group(1), alternate.group()))
    # Natural explicit labels can precede a relative clause or follow the number.
    # Never treat an unlabelled number in a customer-only transcript as an order.
    for pattern in (
        r"\border\s+(?:id|number)\s+of\b[^\n.;!?]{1,90}?\bis\s+(\d{4,20})(?!\w|[-/]\d|\.\d)",
        r"(?<![\w./-])(\d{4,20})\s+is\s+(?:my|the)\s+order\s*(?:id|number)?\b",
    ):
        matches.extend((m.group(1), m.group()) for m in re.finditer(pattern, message, re.I))
    if pending == "order_id" and re.fullmatch(r"\s*\d{4,20}[.!]?\s*", message):
        matches.append((message.strip().rstrip(".!"), message.strip()))
    values = {value for value, _ in matches}
    if len(values) != 1:
        return None, len(values) > 1, ""
    value, quote = matches[0]
    return value, False, quote


@dataclass
class ScopedFacts:
    values: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    states: dict[str, str] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    blocked: bool = False


def scoped_conditions(message: str, case: ReturnCase, pending: str | None) -> ScopedFacts:
    result = ScopedFacts()
    if INJECTION.search(message) or UNRESOLVED_SUBJECT.search(message):
        result.blocked = True
        return result
    plain = message.strip().casefold().rstrip(" .!?")
    if (
        pending in BOOL_FIELDS
        and plain in {"yes", "yep", "yeah", "no", "nope"}
        and not message.rstrip().endswith("?")
    ):
        result.values[pending] = plain in {"yes", "yep", "yeah"}
        result.evidence[pending] = message
        result.states[pending] = "stated"
        return result
    for match in re.finditer(r"[^.;!?\n]+", message):
        quote = match.group().strip()
        text = quote.casefold().rsplit(":", 1)[-1].strip()
        if match.end() < len(message) and message[match.end()] == "?":
            continue
        if COMPLEX_NEGATION.search(text):
            continue
        if UNCERTAIN.search(text):
            if (
                pending in BOOL_FIELDS
                and pending not in result.values
                and not re.search(r"\b(?:who|cause)\b", text)
            ):
                result.states[pending] = "uncertain"
                result.evidence[pending] = quote
            continue
        if HYPOTHETICAL.search(text) or re.match(
            r"\s*(?:are|is|can|could|do|does|what|when|why)\b", text
        ):
            continue
        # Subject distinction prevents a damaged tag/box becoming item damage.
        tag = bool(re.search(r"\btags?\b", text))
        package = bool(re.search(r"\b(?:package|packaging|box|parcel)\b", text))
        item = not tag and not package
        candidates: dict[str, bool] = {}
        if "stain" in text or re.search(r"\bis clean\b", text):
            neg = bool(
                re.search(
                    r"\b(?:no|zero|neither)\b[^;.!?]*\bstain|\bnot\b[^;.!?]*\bstain|"
                    r"\b(?:isn't|is not)\b[^;.!?]*\bstain|stain.free",
                    text,
                )
            )
            candidates["stained"] = not neg and "stain" in text
            if re.search(r"\bis clean\b", text):
                candidates["stained"] = False
        if tag:
            if re.search(
                r"attach|fasten|detach|removed|missing|taken off|cut off|hang from|"
                r"tags? (?:are |is )?still on|tags? remain on",
                text,
            ):
                detached = bool(
                    re.search(
                        r"no longer|not (?:still )?attached|(?:aren't|isn't|weren't) attached|"
                        r"no tags attached|tags? (?:are |were |is )?missing|"
                        r"detach|taken off|cut off|removed",
                        text,
                    )
                )
                # Explicit negation of removal supports attachment, not integrity.
                not_removed = bool(
                    re.search(
                        r"(?:not|never|nobody has)[^;.!?]*(?:removed|taken off|detached)", text
                    )
                )
                if not re.search(r"(?:not|aren't|isn't) missing", text):
                    candidates["tags_attached"] = not detached or not_removed
            negative_damage = bool(
                re.search(
                    r"\b(?:no|not|none|neither|zero)\b[^;.!?]*(?:damage|torn|tear|holes)|"
                    r"undamaged|intact|perfect condition|free of damage",
                    text,
                )
            )
            if re.search(r"\bnot (?:intact|undamaged)\b|\b(?:aren't|isn't) intact\b", text):
                candidates["tags_intact"] = False
            elif negative_damage:
                candidates["tags_intact"] = True
            elif re.search(r"damag|torn|tear|ripped|broken", text):
                candidates["tags_intact"] = False
        if item:
            negative_damage = bool(
                re.search(
                    r"\b(?:no|not|neither|zero)\b[^;.!?]*(?:damage|tear|holes)|"
                    r"isn't damaged|undamaged|intact|free of damage",
                    text,
                )
            )
            if re.search(r"\bnot (?:intact|undamaged)\b", text):
                candidates["damaged"] = True
            elif negative_damage:
                candidates["damaged"] = False
            elif re.search(
                r"\b(?:damaged|damage|torn|tear|ripped|rip|hole|broken|faulty|crack)\b", text
            ):
                candidates["damaged"] = True
        if re.search(r"\b(?:used|use|wore|worn|wearing|unused)\b", text):
            if re.search(
                r"not used (?:much|outdoors|outside)|not (?:worn|used) (?:often|recently)", text
            ):
                pass
            elif re.search(
                r"\b(?:never|not|haven't|hasn't|didn't|don't|did not|have not|has not)\b"
                r"[^;.!?]*\b(?:use|used|wore|worn)\b|\bunused\b|not once.*worn",
                text,
            ):
                candidates["used"] = False
            elif re.search(
                r"\bi (?:used|wore|spent.*wearing)|\b(?:was|been) (?:used|worn)\b", text
            ):
                candidates["used"] = True
        if re.search(r"unopened|still sealed|not opened", text):
            candidates["opened"] = False
        elif re.search(r"\bopened\b|\b(?:packaging|package|box)\b.*\bopen\b", text):
            candidates["opened"] = True
        for name, value in candidates.items():
            if name in result.values and result.values[name] != value:
                result.values[name] = None
                result.conflicts.append(name)
                result.states[name] = "conflict"
            elif name not in result.conflicts:
                result.values[name], result.evidence[name], result.states[name] = (
                    value,
                    quote,
                    "stated",
                )
    # Origin must itself be asserted; arrival plus a healthy condition is not fault.
    origins: set[str] = set()
    origin_quotes: list[str] = []
    for match in re.finditer(r"[^.;!?\n]+", message):
        text = match.group().strip().casefold()
        if match.end() < len(message) and message[match.end()] == "?":
            continue
        unknown = bool(
            re.search(
                r"(?:don't know|do not know|cannot tell|cannot establish).*\b(?:who|cause)", text
            )
        )
        if unknown:
            origins.add("unknown")
            origin_quotes.append(match.group().strip())
            continue
        if HYPOTHETICAL.search(text) or UNCERTAIN.search(text) or COMPLEX_NEGATION.search(text):
            continue
        customer = bool(
            re.search(
                r"\bi (?:stained|damaged|cut off|removed|caused)\b|"
                r"\bi am .*\bcaused\b|\bmy fault\b|\bcaused by me\b",
                text,
            )
        ) and not re.search(r"\b(?:not|never|didn't|did not|isn't)\b", text)
        arrival = bool(re.search(r"\b(?:arrived|delivered|delivery)\b", text))
        adverse = bool(re.search(r"\b(?:stained|damaged|missing|removed|torn|problems)\b", text))
        negated = bool(re.search(r"\b(?:not|no|never|wasn't|weren't|isn't|without)\b", text))
        for origin_label, supported in (
            ("customer", customer),
            ("pre_existing", arrival and adverse and not negated),
        ):
            if supported:
                origins.add(origin_label)
                origin_quotes.append(match.group().strip())
    origin = next(iter(origins)) if len(origins) == 1 else None
    if len(origins) > 1:
        result.conflicts.append("condition_origin")
        result.states["condition_origin"] = "conflict"
    if pending == "condition_origin" and plain in {"unknown", "i don't know", "i'm not sure"}:
        origin = "unknown"
    elif pending == "condition_origin" and plain in {"customer", "i caused it"}:
        origin = "customer"
    elif pending == "condition_origin" and plain in {"pre_existing", "already present on delivery"}:
        origin = "pre_existing"
    if origin:
        result.values["condition_origin"] = origin
        result.evidence["condition_origin"] = origin_quotes[0] if origin_quotes else message
        result.states["condition_origin"] = "stated"
    return result
