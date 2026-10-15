"""Re-score frozen raw runs uniformly, without re-calling models or tuning on held-out data."""

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from app.domain.models import ReturnCase
from app.extractors.rules import RuleBasedExtractor
from scripts.evaluate_reliability import CRITICAL, summarize

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "data/evaluation_runs/reliability-v2"
# The selected item name is context, not a target in these focused questions.
# A legacy extractor repeating a name in the message is not hallucinating it.
COMMON = {"intent", "order_id", "reason", "used", "opened", "damaged", "wants_human"}


def asserted(field, value):
    default = "unclear" if field == "intent" else False if field == "wants_human" else None
    return value != default


def score_claims(rows, fields):
    filled = unsupported = 0
    for row in rows:
        for field in fields:
            actual = row["actual"].get(field)
            if asserted(field, actual):
                filled += 1
                unsupported += not asserted(field, row["expected"][field])
    return {"unsupported": unsupported, "asserted": filled, "rate": unsupported / max(filled, 1)}


async def verify_rule_equivalence(rows):
    extractor = RuleBasedExtractor()
    for row in rows:
        facts = await extractor.extract(
            row["text"],
            ReturnCase(session_id=uuid4(), **row["current_case"]),
            row["pending_question"],
        )
        if facts.model_dump(mode="json") != row["actual"]:
            return False
    return True


def report():
    results, hashes, ids = {}, {}, None
    for variant in ("legacy", "focused", "hybrid", "rules"):
        path = RUNS / f"heldout-{variant}/{variant}.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        current_ids = [row["id"] for row in rows]
        assert len(rows) == 120 and len(set(current_ids)) == 120
        if ids is None:
            ids = current_ids
        assert ids == current_ids, "Runs are not paired"
        result = summarize(rows)
        result["fallback_requests"] = sum(
            row["path"] == "model_error_rules_fallback" for row in rows
        )
        result["assertions_common_legacy_fields"] = score_claims(rows, COMMON)
        result["assertions_all_fields"] = score_claims(rows, set(rows[0]["expected"]))
        known_scores = {}
        for field in CRITICAL:
            labeled = [row for row in rows if row["expected"][field] is not None]
            known_scores[field] = {
                "correct": sum(
                    row["actual"].get(field) == row["expected"][field] and not row["error"]
                    for row in labeled
                ),
                "total": len(labeled),
            }
        result["critical_non_null_scores"] = known_scores
        result["critical_non_null_macro_accuracy"] = sum(
            score["correct"] / max(score["total"], 1) for score in known_scores.values()
        ) / len(known_scores)
        result["usage_incomplete_requests"] = sum(
            row["model_called"] and not row["usage"] for row in rows
        )
        results[variant] = result
        hashes[variant] = hashlib.sha256(path.read_bytes()).hexdigest()
    baseline = results["legacy"]["assertions_common_legacy_fields"]["rate"]
    final_rules_match = asyncio.run(verify_rule_equivalence(rows))
    candidate = results["hybrid"]
    public = {
        name: json.loads((ROOT / f"docs/results/reliability-abcd-{name}-32.json").read_text())
        for name in ("legacy", "focused")
    }
    output = {
        "candidate_revision": "64f845d",
        "kind": "authored template-held-out supplement; NOT official benchmark gold",
        "label_review": "pending_human_review",
        "common_claim_fields": sorted(COMMON),
        "out_of_target_fields": ["item_name"],
        "raw_run_sha256": hashes,
        "results": results,
        "paired_public_regression": {
            "legacy": public["legacy"]["overall"],
            "focused": public["focused"]["overall"],
            "input_sha256": public["legacy"]["config"]["input_sha256"],
            "note": "Same 32 native conversations, seed 42; official grounded labels only.",
        },
        "measured_gates": {
            "final_rule_outputs_match_frozen_heldout": final_rules_match,
            "hybrid_critical_macro_at_least_90_percent": candidate["critical_macro_accuracy"]
            >= 0.9,
            "unsupported_common_assertions_not_above_baseline": candidate[
                "assertions_common_legacy_fields"
            ]["rate"]
            <= baseline,
            "no_hybrid_provider_failures": (
                candidate["provider_failures"] == 0 and candidate["fallback_requests"] == 0
            ),
            "critical_non_null_macro_at_least_90_percent": (
                candidate["critical_non_null_macro_accuracy"] >= 0.9
            ),
            "paired_public_supported_accuracy_not_regressed": (
                all(run["complete"] for run in public.values())
                and public["legacy"]["config"]["input_sha256"]
                == public["focused"]["config"]["input_sha256"]
                and public["focused"]["overall"]["labeled_slot_accuracy"]
                >= public["legacy"]["overall"]["labeled_slot_accuracy"]
            ),
        },
        "release_status": "blocked",
        "external_gates": {
            "human_label_audit": "not_done",
            "Jetstream2_PostgreSQL_and_CPU_model_smoke": "not_run",
            "restored_cloud_backup_validation": "not_run",
        },
        "limitations": [
            "Legacy lacks new fields: compare common-field assertions, not apparel improvement.",
            "Raw counts include out-of-target item_name; not all extras are hallucinations.",
            "Critical macro accuracy includes unknowns; non-null scores expose all-null shortcuts.",
            "24 templates x 5 catalog variants are not 120 independent customer conversations.",
            "Metal timings are not cloud CPU timings; failed-call token totals are incomplete.",
            "Quote validation checks source location, not entailment or physical condition.",
        ],
    }
    target = ROOT / "docs/results/reliability-release.json"
    target.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"measured_gates": output["measured_gates"], "release_status": "blocked"}))


if __name__ == "__main__":
    report()
