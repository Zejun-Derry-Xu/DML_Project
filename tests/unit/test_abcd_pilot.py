from scripts.abcd_pilot import annotate
from scripts.evaluate_abcd_pilot import score


def test_pilot_fields_require_utterance_evidence() -> None:
    scenario = {
        "order": {"order_id": "1234567890"},
        "product": {"names": ["Acme boots"]},
    }
    fields, reasons = annotate(
        "I want to return Acme boots; order 1234567890 is too tight.", scenario
    )
    assert fields["order_id"]["quote"] == "1234567890"
    assert fields["item_name"]["quote"] == "Acme boots"
    assert fields["reason"]["value"] == "does_not_fit"
    assert reasons == []


def test_pilot_does_not_infer_unspoken_order_or_wrong_color_reason() -> None:
    scenario = {
        "order": {"order_id": "1234567890"},
        "product": {"names": ["Acme boots"]},
    }
    fields, reasons = annotate("I want to return it. The color is wrong.", scenario)
    assert "order_id" not in fields
    assert "item_name" not in fields
    assert "reason" not in fields
    assert "order_id_not_stated_in_selected_turn" in reasons


def test_reason_score_counts_wrong_value_as_false_positive_and_negative() -> None:
    assert score(["does_not_fit", None], ["wrong_item", "defective"]) == {
        "tp": 0,
        "fp": 2,
        "fn": 1,
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
    }
