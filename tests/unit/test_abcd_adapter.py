from app.evaluation.abcd import AbcdExample
from app.evaluation.abcd_adapter import mvp_order_id_projection


def test_identifier_adapter_preserves_unknowns_and_original_source():
    source = AbcdExample(
        sample_id="abcd:dev:1:self_contained",
        split="dev",
        convo_id=1,
        task="self_contained",
        message="My order is 1234567890. I have not used it.",
        turn_index=None,
        subflow="return_size",
        expected={"order_id": "1234567890", "used": False, "damaged": None},
        label_mask={"order_id": True, "used": True, "damaged": True},
        evidence={},
        current_case={"order_number": "9876543210"},
    )
    adapted = mvp_order_id_projection([source])[0]
    assert source.expected["order_id"] == "1234567890"
    assert "ORD-" not in source.message
    assert adapted.expected == {"order_id": "ORD-1234567890", "used": False, "damaged": None}
    assert "ORD-1234567890" in adapted.message
    assert adapted.current_case["order_number"] == "ORD-9876543210"
