"""Summarize bounded comparisons without silently treating partial results as passes."""

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITES = ("apparel-dev", "apparel-validation", "apparel-regression", "abcd-full", "abcd-replay")


def build(root=ROOT):
    lines = [
        "# Bounded v4 guardrails — results and deployment handoff",
        "",
        "Release: BLOCKED pending human label audit, all quality gates and manual CPU acceptance.",
        "No main merge or Jetstream changes. Qwen3:4B is unchanged; policy is mvp-2.0.0.",
        "Strict ABCD scoring is unchanged. New authored labels are automatically provisional.",
        "Existing 180 apparel examples are regression material, not a new blind test.",
        "",
        "| Dataset | Revision | Completed | Explicit apparel macro | Order exact | Item strict | "
        "Calls | Input/output tokens | p50/p95 seconds |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for suite in SUITES:
        for revision in ("v3", "v4"):
            path = root / f"docs/results/optimization-guardrails-{suite}-{revision}-hybrid.json"
            if not path.exists():
                lines.append(f"| {suite} | {revision} | NOT RUN | — | — | — | — | — | — |")
                continue
            report = json.loads(path.read_text())
            result = report["results"]

            def percent(value):
                return "—" if value is None else f"{value:.1%}"

            fields = result["per_field"]
            latency = result.get("latency_seconds") or {}
            timing = f"{latency['p50']:.2f}/{latency['p95']:.2f}" if latency else "—"
            complete = f"{result['examples']}/{report['selected']}"
            if not report["complete"]:
                complete += " PARTIAL"
            tokens = result["tokens"]
            lines.append(
                f"| {suite} | {revision} | {complete} | "
                f"{percent(result['critical_known_macro'])} | "
                f"{percent(fields.get('order_id', {}).get('accuracy'))} | "
                f"{percent(fields.get('item_name', {}).get('accuracy'))} | "
                f"{result['model_calls']} | {tokens['prompt_eval_count']}/"
                f"{tokens['eval_count']} | {timing} |"
            )
    lines += [
        "",
        "## Field diagnostics (reviewed masks only)",
        "",
        "| Dataset/revision | Field | Scored | Correct | Evidence rejection | Fusion loss* |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for suite in SUITES:
        for revision in ("v3", "v4"):
            name = f"guardrails-{suite}-{revision}-hybrid"
            raw = root / f"data/evaluation_runs/extraction-optimization/{name}.jsonl"
            if not raw.exists():
                continue
            counts = {}
            errors = Counter()
            for line in raw.read_text().splitlines():
                row = json.loads(line)
                errors.update(row.get("error_categories", {}).values())
                for field, expected in row["expected"].items():
                    if not row["label_mask"].get(field):
                        continue
                    stat = counts.setdefault(field, Counter())
                    stat["scored"] += 1
                    correct = row["actual"].get(field) == expected
                    stat["correct"] += int(correct)
                    stat["rejected"] += int(
                        field in row.get("diagnostics", {}).get("rejected_fields", [])
                    )
                    stat["fusion_loss"] += int(
                        not correct and row.get("rule_candidates", {}).get(field) == expected
                    )
            for field, stat in sorted(counts.items()):
                lines.append(
                    f"| {suite}/{revision} | {field} | {stat['scored']} | "
                    f"{stat['correct']} | {stat['rejected']} | {stat['fusion_loss']} |"
                )
            lines.append(f"\nAggregate error categories, {suite}/{revision}: {dict(errors)}.\n")
    lines += [
        "",
        "*Fusion loss counts a correct rule field made incorrect by the final result; "
        "it does not prove the model alone caused the error. Evidence rejection counts "
        "all rejected candidates, not just correct candidates rejected.",
        "",
        "## Interpretation boundaries",
        "",
        "- ABCD full inputs concatenate customer utterances. Replay uses actual preceding agent "
        "questions and only the extractor's own accumulated facts. Neither is closed-loop business "
        "end-to-end success.",
        "- Original teacher-forced replay results remain in extraction-optimization-summary.md; "
        "do not merge their scores with predicted-history replay.",
        "- Report order and item targets separately (90%/80%). Generic/branded names without a "
        "verified unique SKU remain unresolved; no hidden catalog is supplied to ABCD.",
        "- Raw traces remain ignored locally. Full texts and model outputs are not added to "
        "operational logs or Git.",
        "- Latencies measured on this Mac's Apple Metal are not Jetstream2 CPU performance. "
        "Cold/warm CPU measurements remain pending.",
        "- Missing results, errors and unaudited labels do not authorize release. One repair "
        "cycle only; remaining research belongs in backlog.",
        "",
        "See ../returnflow-v4-deployment-handoff.md for both diagrams and manual acceptance. "
        "No automatic database downgrade, restore-over-live or volume deletion is permitted.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    target = ROOT / "docs/results/extraction-guardrails-v4-summary.md"
    target.write_text(build())
    print(target)
