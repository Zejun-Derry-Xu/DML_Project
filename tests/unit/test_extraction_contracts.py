import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.domain.models import ReturnCase, ReturnFacts, ReturnReason
from app.domain.state_machine import next_missing_field
from app.extractors.contracts import EvidenceFacts, grounded, prompt
from app.extractors.fake import FakeExtractor
from app.extractors.hybrid import HybridExtractor
from app.extractors.rules import RuleBasedExtractor
from scripts.build_reliability_fixture import build
from scripts.evaluate import meaningful


def test_fixture_is_frozen_complete_and_group_split():
    rows = build()
    assert len(rows) == 240
    assert len({row["text"] for row in rows}) == 224  # yes/no substitutions share surface text
    groups = {
        split: {row["template_group"] for row in rows if row["split"] == split}
        for split in ("dev", "test")
    }
    assert not groups["dev"] & groups["test"]
    frozen = Path(__file__).parents[1] / "fixtures/extraction_reliability_v2.json"
    assert json.loads(frozen.read_text()) == rows
    assert all(set(row["expected"]) == set(ReturnFacts.model_fields) for row in rows)


def test_false_context_and_real_question_are_retained():
    text = prompt(
        "They are fine.",
        ReturnCase(
            session_id=uuid4(),
            used=False,
            item_category="apparel",
            question_prompt="Are the tags intact?",
        ),
        "tags_intact",
    )
    assert '"used": false' in text
    assert "Are the tags intact?" in text
    assert "tags_intact" in text and "false is an explicit negative" in text
    assert meaningful({"used": False, "wants_human": False}) == {"used": False}


def test_evidence_is_required_but_not_claimed_to_prove_entailment():
    facts, rejected = grounded(
        EvidenceFacts(
            facts=ReturnFacts(used=False, tags_intact=True), evidence={"used": "never wore"}
        ),
        "I never wore it.",
        "used",
    )
    assert facts.used is False
    assert facts.tags_intact is None and rejected == ["tags_intact"]


@pytest.mark.asyncio
async def test_disagreement_is_not_silently_rule_precedence():
    extractor = HybridExtractor(FakeExtractor(ReturnFacts(stained=False, used=False)))
    result = await extractor.extract("It is stained.", ReturnCase(session_id=uuid4()), None)
    assert result.stained is None
    assert extractor.last_conflicts == ["stained"]


@pytest.mark.asyncio
async def test_clear_rule_answer_saves_model_call():
    class Exploding:
        async def extract(self, *args):
            raise AssertionError("A clear button-like answer must not call the model")

    extractor = HybridExtractor(Exploding())
    result = await extractor.extract("No.", ReturnCase(session_id=uuid4()), "stained")
    assert result.stained is False
    assert extractor.last_path == "rules_sufficient"


@pytest.mark.asyncio
async def test_tag_damage_is_not_item_damage():
    result = await RuleBasedExtractor().extract(
        "The tags are damaged.", ReturnCase(session_id=uuid4()), "tags_intact"
    )
    assert result.tags_intact is False
    assert result.damaged is None and result.reason is None


@pytest.mark.asyncio
async def test_complete_apparel_does_not_require_usage_or_model():
    class Exploding:
        async def extract(self, *args):
            raise AssertionError("All required condition facts are explicit")

    extractor = HybridExtractor(Exploding())
    result = await extractor.extract(
        "Return ORD-1010 because it doesn't fit. It has no stains. "
        "The tags are attached. The tags are intact. It is not damaged.",
        ReturnCase(session_id=uuid4(), item_category="apparel"),
        None,
    )
    assert result.used is None and result.stained is False
    assert extractor.last_path == "rules_sufficient"


def test_state_helper_uses_apparel_conditions_not_usage():
    case = ReturnCase(
        session_id=uuid4(),
        order_number="ORD-1010",
        item_category="apparel",
        reason=ReturnReason.DOES_NOT_FIT,
        used=True,
    )
    assert next_missing_field(case) == "stained"
    case.tags_attached = False
    assert next_missing_field(case) == "condition_origin"
    case.condition_origin = "unknown"
    assert next_missing_field(case) is None  # policy routes this to human review
