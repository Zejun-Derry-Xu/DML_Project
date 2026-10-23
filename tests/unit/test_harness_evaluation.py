import pytest

from app.config import Settings
from scripts.analyze_apparel_harness import attribution
from scripts.evaluate_apparel_harness import load_samples, make_extractor, metrics, select_candidate


def row(name, actual, expected=None, error=None, rejected=None):
    return {
        "id": name,
        "actual": actual,
        "expected": expected or {"damaged": False},
        "error": error,
        "seconds": 1.0,
        "usage": {},
        "rejected_fields": rejected or [],
        "trace": {"stage": "wire_contract" if error else "complete"},
    }


def test_dataset_counts_grouping_and_reviewed_ranges():
    old, new = load_samples()
    assert len(old) == len(new) == 48
    assert len({r["group"] for r in new}) == 48
    assert all(len(r["labels"]) <= 2 for r in new)
    assert len({r["id"] for r in old + new}) == 96
    assert any(r["labels"].get("used") is False for r in new)
    assert all("label_mask" in r for r in old)


def test_metrics_keep_false_failures_null_and_rejection_losses_separate():
    report = metrics(
        [
            row("a", {"damaged": False}),
            row("b", {}, rejected=["damaged"]),
            row("c", {"damaged": True}, {"damaged": None}),
            row("d", {}, {"damaged": None}, error="TimeoutError"),
        ]
    )
    assert report["known_macro"] == 0.5
    assert report["known_total"] == 2
    assert report["known_wrong_also_rejected"] == 1
    assert report["unsupported_on_reviewed_absence"] == 1
    assert report["reviewed_null_correct"] == 0
    assert report["errors"] == 1
    assert report["failure_stages"] == {"wire_contract": 1}
    assert report["rows_without_usage"] == 4


def test_selection_uses_dev_scores_and_never_claims_release_approval():
    good = [row("a", {"damaged": False}), row("b", {}, {"damaged": None})]
    unsafe = [row("a", {"damaged": False}), row("b", {"damaged": True}, {"damaged": None})]
    result = select_candidate({"legacy": good, "typed": unsafe, "span_ids": good})
    assert result["selected"] == "span_ids"
    assert result["passed_dev_nonregression"] is True
    result = select_candidate({"legacy": good, "typed": unsafe, "span_ids": unsafe})
    assert result["passed_dev_nonregression"] is False


def test_single_attempt_for_all_experimental_variants():
    for variant in ("legacy", "typed", "span_ids"):
        assert make_extractor(Settings(), variant).max_attempts == 1
    with pytest.raises(ValueError, match="Unknown"):
        make_extractor(Settings(), "invented")


def test_attribution_does_not_count_boolean_strings_as_correct():
    a = row("a", {}, rejected=["damaged"])
    a["trace"]["parsed_candidates"] = {
        "facts": [
            {"field": "damaged", "value": "false", "state": "stated", "evidence": "no damage"}
        ]
    }
    b = row("b", {}, rejected=["damaged"])
    b["trace"]["parsed_candidates"] = {
        "facts": [{"field": "damaged", "value": False, "state": "stated", "evidence": "invented"}]
    }
    result = attribution([a, b])
    assert result["raw_typed_correct_candidates"] == 1
    assert result["correct_candidates_lost_in_validation"] == 1
    assert result["label_like_boolean_strings_not_counted_correct"] == 1
    assert result["accepted_correct"] == 0
