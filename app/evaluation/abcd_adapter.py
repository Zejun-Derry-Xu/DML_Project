"""Explicit ID-format compatibility projection; never changes native benchmark sources."""

import re
from dataclasses import replace

from app.evaluation.abcd import AbcdExample


def mvp_order_id_projection(examples: list[AbcdExample]) -> list[AbcdExample]:
    adapted = []
    for row in examples:
        expected = dict(row.expected)
        current_case = dict(row.current_case)
        message = row.message
        identifier = expected.get("order_id")
        if isinstance(identifier, str) and identifier.isdigit():
            canonical = f"ORD-{identifier}"
            message = re.sub(r"(?<!\w)" + re.escape(identifier) + r"(?!\w)", canonical, message)
            expected["order_id"] = canonical
        previous_id = current_case.get("order_number")
        if previous_id and previous_id.isdigit():
            current_case["order_number"] = f"ORD-{previous_id}"
        adapted.append(replace(row, message=message, expected=expected, current_case=current_case))
    return adapted
