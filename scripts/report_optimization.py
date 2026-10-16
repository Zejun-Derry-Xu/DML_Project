"""Publish aggregate progress honestly; missing/partial evaluations never pass gates."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs/results"
SUITES = {
    "Apparel development (120)": "dev31-final",
    "Apparel validation (180)": "validation31-frozen",
    "ABCD project reserve (192 train conversations)": "abcd-reserve-frozen",
    "ABCD official test (612 scorable full conversations)": "abcd-public-frozen",
    "ABCD observed context (32 conversations / 293 turns)": "abcd-context-frozen",
}


def score(value):
    return "—" if value is None else f"{value:.1%}"


def build():
    lines = [
        "# Extraction optimization — measured progress",
        "",
        f"Generated {datetime.now(UTC).isoformat()}.",
        "",
        "Status: **BLOCKED**. Automatic/provisional labels are not human-audited. "
        "Missing runs and unmet gates are not passes. No merge or cloud deployment.",
        "",
        "Candidate extractor is frozen at `a47065a`; policy remains `mvp-2.0.0`. "
        "Earlier development runs retain their own dirty-tree source hashes. "
        "Local Apple Metal timings must not be presented as Jetstream CPU timings.",
    ]
    for title, prefix in SUITES.items():
        lines += [
            "",
            f"## {title}",
            "",
            "| Mode | Completed | Explicit apparel macro | Order exact | Item strict | "
            "Unsupported fills* | Model calls | Errors / fallbacks | "
            "Native input / output tokens | p50 / p95 seconds |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for variant in ("v2-hybrid", "v3-rules", "v3-model", "v3-hybrid"):
            path = RESULTS / f"optimization-{prefix}-{variant}.json"
            if not path.exists():
                lines.append(f"| {variant} | NOT RUN | — | — | — | — | — | — | — | — |")
                continue
            report = json.loads(path.read_text())
            result = report["results"]
            fields = result["per_field"]
            order = fields.get("order_id", {}).get("accuracy")
            item = fields.get("item_name", {}).get("accuracy")
            latency = result.get("latency_seconds") or {}
            times = f"{latency['p50']:.2f} / {latency['p95']:.2f}" if latency else "—"
            tokens = result["tokens"]
            fills = (
                str(result["audited_unsupported_fills"])
                if result.get("audited_absence_checks")
                else "unreviewed"
            )
            complete = f"{result['examples']}/{report['selected']}"
            if not report["complete"]:
                complete += " PARTIAL"
            lines.append(
                f"| {variant} | {complete} | {score(result['critical_known_macro'])} | "
                f"{score(order)} | {score(item)} | {fills} | {result['model_calls']} | "
                f"{result['errors']} / {result['provider_fallbacks']} | "
                f"{tokens['prompt_eval_count']} / {tokens['eval_count']} | {times} |"
            )
    lines += [
        "",
        "## Interpretation and remaining gates",
        "",
        "- The targets are ≥90% explicit apparel macro, ≥90% native order exact, "
        "and ≥80% item strict accuracy, reported separately. Partial scores are provisional.",
        "- *ABCD lacks audited absent-condition labels: a zero hallucination count "
        "cannot establish zero hallucination risk. Its missing labels stay unreviewed.",
        "- Full-conversation ABCD inputs concatenate customer turns, not agent questions. "
        "Some numeric answers are unidentifiable without that missing context. We do not "
        "invent order cues or replace native IDs with ORD prefixes to inflate accuracy.",
        "- Context testing supplies the actual preceding agent text. Its prior case facts "
        "are teacher-forced observed-label context from the existing projection, not "
        "self-accumulated agent state. It is NOT closed-loop end-to-end task success.",
        "- Fixed 4096-token context and 512-token output budgets can limit long inputs; "
        "provider failures and rule fallbacks are reported, never dropped from denominators.",
        "- All model work is serial Qwen3:4B, thinking disabled. Native counters exclude "
        "any failed transport for which the provider returned no counters.",
        "- Human label audit, paired no-regression checks, all remaining model runs, "
        "and manual Jetstream PostgreSQL/API/UI/Qwen acceptance remain required before release.",
        "",
        "## Reproduction and rollback",
        "",
        "Run from the repository with the pinned official ABCD source/prepared projection "
        "and the ignored reserve JSONL available. Select the report's recorded code revision "
        "and source/model hashes. Never overwrite reports or change labels after validation.",
        "",
        "```bash",
        ".venv/bin/python -m scripts.evaluate_optimization --dataset apparel-v31 "
        "--split validation --revision v3 --mode hybrid --name validation31-frozen-v3-hybrid",
        ".venv/bin/python -m scripts.evaluate_optimization --dataset abcd-reserve "
        "--revision v3 --mode hybrid --name abcd-reserve-frozen-v3-hybrid",
        ".venv/bin/python -m scripts.evaluate_optimization --dataset abcd-public "
        "--revision v3 --mode model --name abcd-public-frozen-v3-model",
        ".venv/bin/python -m scripts.evaluate_optimization --dataset abcd-context "
        "--revision v3 --mode hybrid --name abcd-context-frozen-v3-hybrid",
        ".venv/bin/python -m scripts.report_optimization",
        "```",
        "",
        "Repeat the same frozen inputs with `v2/hybrid`, `v3/rules`, `v3/model`, and "
        "`v3/hybrid` as listed above. One process at a time. Every input is flushed before "
        "the next request; the identical command resumes only if its recorded configuration "
        "matches. Otherwise choose a new name and retain the old partial result.",
        "",
        "Checkpoint 1: `6a44129` (baseline/data); checkpoint 2: `a47065a` (functionality). "
        "Main remains unchanged. For application rollback, preserve work and select a reviewed "
        "previous code revision; do not reset data, delete volumes, downgrade the schema, "
        "or replay a live return. See `docs/jetstream-v2-runbook.md` "
        "before any future cloud action.",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=RESULTS / "extraction-optimization-summary.md"
    )
    args = parser.parse_args()
    args.output.write_text(build())
    print(args.output)


if __name__ == "__main__":
    main()
