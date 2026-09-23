import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.domain.models import ReturnCase
from app.extractors.rules import RuleBasedExtractor

CASES = json.loads((Path(__file__).parents[1] / "fixtures" / "extraction_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[case["text"][:35] for case in CASES])
async def test_labeled_extraction_cases(case):
    result = await RuleBasedExtractor().extract(
        case["text"],
        ReturnCase(session_id=uuid4()),
        case.get("pending_question"),
    )
    actual = result.model_dump(mode="json")
    for field, expected in case["expected"].items():
        assert actual[field] == expected
