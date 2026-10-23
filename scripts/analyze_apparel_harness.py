"""Offline attribution of private harness traces; no model requests or score relaxation."""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def equal_typed(value: Any, expected: Any) -> bool:
    return type(value) is type(expected) and value == expected


def attribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    stages: Counter[str] = Counter()
    known = raw_correct = accepted_correct = lost_correct = bool_strings = 0
    failures = []
    for row in rows:
        trace = row.get("trace", {})
        for rejection in trace.get("rejections", []):
            reasons[rejection["reason"]] += 1
        if row["error"]:
            stages[trace.get("stage", "unknown")] += 1
        parsed = trace.get("parsed_candidates")
        facts = parsed.get("facts", []) if isinstance(parsed, dict) else []
        if not isinstance(facts, list):
            facts = []
        wrong = {}
        for field, expected in row["expected"].items():
            candidates = [f for f in facts if isinstance(f, dict) and f.get("field") == field]
            candidate = candidates[0] if len(candidates) == 1 else {}
            actual = row["actual"].get(field)
            if expected is not None:
                known += 1
                raw_ok = candidate.get("state") == "stated" and equal_typed(
                    candidate.get("value"), expected
                )
                final_ok = equal_typed(actual, expected) and not row["error"]
                raw_correct += raw_ok
                accepted_correct += final_ok
                lost_correct += raw_ok and not final_ok
                bool_strings += (
                    type(expected) is bool
                    and candidate.get("state") == "stated"
                    and type(candidate.get("value")) is str
                    and candidate["value"].lower() == str(expected).lower()
                )
            if not equal_typed(actual, expected) or row["error"]:
                wrong[field] = {"expected": expected, "accepted": actual, "candidate": candidate}
        if wrong or row["error"]:
            failures.append(
                {
                    "id": row["id"],
                    "error": row["error"],
                    "wrong": wrong,
                    "rejections": trace.get("rejections", []),
                }
            )
    return {
        "known_labels": known,
        "raw_typed_correct_candidates": raw_correct,
        "accepted_correct": accepted_correct,
        "correct_candidates_lost_in_validation": lost_correct,
        "label_like_boolean_strings_not_counted_correct": bool_strings,
        "rejection_reasons_all_fields": dict(reasons),
        "failure_stages": dict(stages),
        "failures": failures,
        "warning": (
            "Raw typed agreement is not semantic proof; label-like strings are NOT scored correct"
        ),
    }


def analyze(run: Path) -> dict[str, Any]:
    if not run.resolve().is_relative_to((ROOT / "data/evaluation_runs").resolve()):
        raise ValueError("Private analysis must remain inside data/evaluation_runs")
    report = json.loads((run / "report.json").read_text())
    rows = [json.loads(line) for line in (run / "traces.jsonl").read_text().splitlines()]
    return {
        "run_status": report["status"],
        "formal_qualification": False,
        "selected": report["selection"],
        "groups": {
            f"{variant}/{split}": attribution(
                [row for row in rows if row["variant"] == variant and row["split"] == split]
            )
            for variant, split in sorted({(r["variant"], r["split"]) for r in rows})
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    result = analyze(args.run)
    (args.run / "attribution.json").write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {
                key: {k: v for k, v in body.items() if k != "failures"}
                for key, body in result["groups"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
