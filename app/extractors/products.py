"""Observed retail product spans; no catalog identities or benchmark labels."""

import re

PRODUCT = re.compile(
    r"\b(?:(?:[A-Z][\w-]+[_\s]+){0,3})"
    r"(?i:shirts?|jeans|jackets?|boots?|shoes?|pants|trousers|dresses|dress|sweaters?|"
    r"coats?|skirts?|shorts|socks|hoodies|hoodie|sneakers?|sandals?|headphones?|"
    r"cables?|backpacks?|bags?|mugs?|laptops?)\b"
)
LOWER_PRODUCT = re.compile(
    r"\b(?:shirts?|jeans|jackets?|boots?|shoes?|pants|trousers|dresses|dress|sweaters?|"
    r"coats?|skirts?|shorts|socks|hoodies|hoodie|sneakers?|sandals?|headphones?|"
    r"cables?|backpacks?|bags?|mugs?|laptops?)\b",
    re.I,
)


def product_span(message: str) -> str | None:
    explicit = re.search(r"\b(?:product|item)\s*:\s*(.+?)(?:\s+brand\s*:|[.;\n]|$)", message, re.I)
    if explicit:
        return explicit.group(1).strip()
    spans = [
        re.sub(r"^(?:the|my|a|an|this|that|these|those)\s+", "", match.group(), flags=re.I)
        for match in PRODUCT.finditer(message)
    ]
    spans = [re.sub(r"^ORD[-\s]?\d+\s+", "", span, flags=re.I) for span in spans]
    if not spans:
        spans = [match.group() for match in LOWER_PRODUCT.finditer(message)]
    # Multiple product types are not a unique selected product. Same-type brand
    # variants also require clarification rather than choosing the longest.
    heads = {match.group().casefold() for match in LOWER_PRODUCT.finditer(message)}
    named = {span.casefold().replace("_", " ") for span in spans if " " in span or "_" in span}
    if len(heads) != 1 or len(named) > 1:
        return None
    return max(spans, key=len) if spans else None
