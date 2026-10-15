import hashlib
import json
from pathlib import Path

from scripts.prepare_extraction_optimization import CRITICAL, authored_cases


def test_authored_data_is_frozen_balanced_and_provisional():
    rows = authored_cases()
    root = Path(__file__).parents[2]
    fixture = root / "tests/fixtures/extraction_optimization_v3.json"
    assert json.loads(fixture.read_text()) == rows
    assert len(rows) == 300
    assert len({(r["text"], r["pending_question"]) for r in rows}) == 300
    assert len([r for r in rows if r["split"] == "dev"]) == 120
    validation = [r for r in rows if r["split"] == "validation"]
    assert len(validation) == 180
    for field in CRITICAL[:4]:
        for value in (True, False, None):
            assert sum(r["expected"][field] is value for r in validation) >= 20
    for value in ("customer", "pre_existing", "unknown"):
        assert sum(r["expected"]["condition_origin"] == value for r in validation) >= 20
    for row in rows:
        assert "provisional" in row["label_status"]
        assert all(quote in row["text"] for quote in row["evidence"].values())
        assert row["label_mask"]["item_name"] is False
    manifest = json.loads(
        (root / "tests/fixtures/extraction_optimization_manifest.json").read_text()
    )
    assert manifest["authored_sha256"] == hashlib.sha256(fixture.read_bytes()).hexdigest()
    assert len(set(manifest["reserve_convo_ids"])) == 192
    assert len(set(manifest["contextual_convo_ids"])) == 32
