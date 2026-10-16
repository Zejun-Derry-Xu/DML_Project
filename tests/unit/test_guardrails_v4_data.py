import hashlib
import json
from pathlib import Path

from scripts.prepare_guardrails_v4 import authored_cases


def test_v4_data_is_frozen_and_not_gold_filled():
    root = Path(__file__).parents[2]
    fixture = root / "tests/fixtures/guardrails_v4_apparel.json"
    rows = json.loads(fixture.read_text())
    manifest = json.loads((root / "tests/fixtures/guardrails_v4_manifest.json").read_text())
    assert rows == authored_cases()
    assert len(rows) == 48
    dev = [r for r in rows if r["split"] == "dev"]
    validation = [r for r in rows if r["split"] == "validation"]
    assert len(dev) == len(validation) == 24
    assert not ({r["template_group"] for r in dev} & {r["template_group"] for r in validation})
    for row in rows:
        assert sum(row["label_mask"].values()) == 1
        assert row["evidence"][row["pending_question"]] in row["text"]
        assert "provisional" in row["label_status"]
    assert manifest["apparel_sha256"] == hashlib.sha256(fixture.read_bytes()).hexdigest()
    assert len(set(manifest["selected_convo_ids"])) == 96
    assert len(set(manifest["contextual_convo_ids"])) == 16
    assert set(manifest["contextual_convo_ids"]) <= set(manifest["selected_convo_ids"])
    assert not (
        set(manifest["selected_convo_ids"]) & set(manifest["excluded_model_evaluated_convo_ids"])
    )
    assert manifest["group_counts"] == {"order": 32, "item": 32, "both": 32}
    assert manifest["native_split"] == "train"
    prior = json.loads((root / "tests/fixtures/extraction_optimization_manifest.json").read_text())
    assert manifest["train_projection_sha256"] == prior["abcd_train_sha256"]
    assert not (set(manifest["selected_convo_ids"]) & set(prior["reserve_convo_ids"]))
