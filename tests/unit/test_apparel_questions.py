from app.services.apparel_questions import collection_fields, collection_prompt


def test_collect_only_missing_not_known_unknown_or_conflicting_details():
    assert collection_fields(
        "damaged",
        {"reason_text": "known", "stained": "unknown", "tags_attached": "conflict"},
        enabled=True,
    ) == ["damaged", "tags_intact"]


def test_conflicts_and_conditional_origins_remain_individual_questions():
    assert collection_fields("stained", {"stained": "conflict"}, enabled=True) == ["stained"]
    assert collection_fields("condition_origin", {}, enabled=True) == ["condition_origin"]


def test_no_language_model_keeps_individual_fallback():
    assert collection_fields("stained", {}, enabled=False) == ["stained"]


def test_group_prompt_does_not_reask_answered_fields_or_supply_answers():
    prompt = collection_prompt(["tags_attached", "tags_intact"], "unused")
    assert "still attached and undamaged" in prompt
    assert "stains" not in prompt and "clothing itself" not in prompt
    assert "not sure" in prompt
    assert collection_prompt(["damaged"], "Is the clothing damaged?") == "Is the clothing damaged?"
