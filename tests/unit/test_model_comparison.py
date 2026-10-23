import json

import pytest

from scripts.compare_apparel_models import check_identity, compare, scored_labels


def test_false_is_scored_and_unreviewed_fields_are_not_gold_null():
    assert scored_labels(
        {
            "expected": {"used": False, "damaged": None},
            "label_mask": {"used": True, "damaged": False},
        }
    ) == {"used": False}


def row(name, actual, error=None):
    return {
        "id": name,
        "expected": {"used": False},
        "actual": actual,
        "error": error,
        "seconds": 1.0,
        "usage": {},
    }


def test_pairing_reports_partial_and_errors_are_not_dropped():
    result = compare(
        {"4b": [row("a", {"used": False}), row("b", {})], "8b": [row("a", {}, "TimeoutError")]},
        [{"id": "a"}, {"id": "b"}],
    )
    assert result["paired_rows"] == 1
    assert result["models"]["8b"]["unfinished_ids"] == ["b"]
    assert result["models"]["8b"]["paired"]["errors"] == 1
    assert result["paired_known_macro_delta_second_minus_first"] == -1
    assert result["formal_qualification"] is False


def test_changed_identity_cannot_reuse_old_rows(tmp_path):
    path = tmp_path / "identity.json"
    check_identity(path, {"model": "4b"})
    check_identity(path, {"model": "4b"})
    with pytest.raises(ValueError, match="Changed evaluation"):
        check_identity(path, {"model": "8b"})
    assert json.loads(path.read_text()) == {"model": "4b"}
