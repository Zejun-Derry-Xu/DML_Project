"""Paired bounded v4 tests; observed replay accumulates predictions, never gold."""

import argparse
import asyncio
import hashlib
import json
import platform
import subprocess
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

import httpx

from app.domain.models import ReturnCase, ReturnFacts
from scripts.evaluate_optimization import Capture, summarize
from scripts.guardrails_budget import RepairBudget
from scripts.guardrails_replay import case_for_turn, merge_prediction

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/evaluation_runs/extraction-optimization"


def examples(dataset):
    if dataset.startswith("apparel-"):
        if dataset == "apparel-regression":
            path, split = ROOT / "tests/fixtures/extraction_optimization_v3_1.json", "validation"
        else:
            path = ROOT / "tests/fixtures/guardrails_v4_apparel.json"
            split = "dev" if dataset == "apparel-dev" else "validation"
        return [r for r in json.loads(path.read_text()) if r["split"] == split]
    rows = [json.loads(s) for s in (RUN / "guardrails-v4-abcd.jsonl").read_text().splitlines()]
    wanted = "contextual" if dataset == "abcd-replay" else "self_contained"
    rows = [r for r in rows if r["task"] == wanted]
    return sorted(rows, key=lambda r: (str(r["convo_id"]), r.get("turn_index") or -1))


async def run(args):
    # Snapshot namespace is created only after the original frozen comparison ends.
    if args.revision == "v3":
        from app.extractors.frozen_v3.hybrid import HybridExtractor
        from app.extractors.frozen_v3.ollama import OllamaExtractor
        from app.extractors.frozen_v3.rules import RuleBasedExtractor
    else:
        from app.extractors.hybrid import HybridExtractor
        from app.extractors.ollama import OllamaExtractor
        from app.extractors.rules import RuleBasedExtractor
    provider = OllamaExtractor(
        base_url="http://127.0.0.1:11434/v1", model="qwen3:4b", timeout_seconds=60, retries=0
    )
    extractor = RuleBasedExtractor() if args.mode == "rules" else HybridExtractor(provider)
    selected = examples(args.dataset)
    config = {
        "dataset": args.dataset,
        "revision": args.revision,
        "mode": args.mode,
        "protocol": "guardrails-v4-predicted-history-1",
        "machine": platform.platform(),
        "source_sha256": hashlib.sha256(
            b"".join(
                p.read_bytes()
                for p in sorted((ROOT / "app/extractors").rglob("*"))
                if p.suffix in {".py", ".md"}
            )
        ).hexdigest(),
        "input_sha256": hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest(),
        "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "replay_sha256": hashlib.sha256(
            (ROOT / "scripts/guardrails_replay.py").read_bytes()
        ).hexdigest(),
    }
    if args.mode != "rules":
        async with httpx.AsyncClient(timeout=5) as client:
            manifest = (
                (await client.get("http://127.0.0.1:11434/api/tags")).raise_for_status().json()
            )
            config["model_manifest"] = manifest
            digest = "359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7"
            if not any(
                m["name"] == "qwen3:4b" and m["digest"] == digest for m in manifest["models"]
            ):
                raise ValueError("Pinned Qwen3:4B weights unavailable; no model substitution")
    ident = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    config["git_revision"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    raw = RUN / f"{args.name}.jsonl"
    report = ROOT / f"docs/results/optimization-{args.name}.json"
    rows = [json.loads(s) for s in raw.read_text().splitlines()] if raw.exists() else []
    if any(r["run_id"] != ident for r in rows):
        raise ValueError("Run identity changed; keep old records and use a new name")

    def sample_id(row):
        return row.get("id", row.get("sample_id"))

    if [r["id"] for r in rows] != [sample_id(r) for r in selected[: len(rows)]]:
        raise ValueError("Replay records are not a contiguous chronological prefix")
    history = {}
    if args.dataset == "abcd-replay":
        for row in rows:
            history[row["convo_id"]], _ = merge_prediction(
                history.get(row["convo_id"], {}),
                ReturnFacts.model_validate(row["actual"]),
                row["conflicts"],
            )
    invocation_started = perf_counter()
    processed = 0
    stopped_for_budget = False

    def save():
        report.write_text(
            json.dumps(
                {
                    "config": config,
                    "run_id": ident,
                    "selected": len(selected),
                    "complete": len(rows) == len(selected),
                    "stopped_for_budget": stopped_for_budget,
                    "results": summarize(rows),
                    "replay_history": "own_predictions_only"
                    if args.dataset == "abcd-replay"
                    else "not_applicable",
                    "release_status": "blocked_pending_human_audit_and_quality_gates",
                },
                indent=2,
            )
            + "\n"
        )

    with raw.open("a") as handle:
        for example in selected[len(rows) :]:
            required = 60 if args.mode != "rules" else 0
            if args.max_wall_seconds - (perf_counter() - invocation_started) < required:
                stopped_for_budget = True
                break
            if processed >= args.batch_size:
                break
            convo = example.get("convo_id")
            session = uuid5(NAMESPACE_URL, str(convo or sample_id(example)))
            case = (
                case_for_turn(session, history.get(convo, {}), example)
                if args.dataset == "abcd-replay"
                else ReturnCase(session_id=session, **example.get("current_case", {}))
            )
            pending = example.get("pending_question")
            text = example.get("text", example.get("message"))
            rules = RuleBasedExtractor()
            rule_facts = await rules.extract(text, case, pending)
            provider.last_usage, provider.last_diagnostics, provider.last_trace = {}, {}, {}
            capture, error = Capture(), None
            started = perf_counter()
            try:
                with patch("httpx.AsyncClient", capture.factory):
                    facts = await extractor.extract(text, case, pending)
            except Exception as exc:
                facts, error = ReturnFacts(), type(exc).__name__
            elapsed = perf_counter() - started
            conflicts = getattr(
                extractor, "last_conflicts", getattr(extractor, "ambiguous_fields", [])
            )
            rejected = provider.last_diagnostics.get("rejected_fields", [])
            categories = {}
            for field, gold in example["expected"].items():
                if not example["label_mask"].get(field) or getattr(facts, field) == gold:
                    continue
                categories[field] = (
                    "provider_error"
                    if error
                    else "fusion_conflict"
                    if field in conflicts
                    else "evidence_rejection"
                    if field in rejected
                    else "rule_false_assertion"
                    if getattr(rule_facts, field) is not None and getattr(rule_facts, field) != gold
                    else "omission"
                    if getattr(facts, field) is None
                    else "semantic_or_span_error"
                )
            cross_turn = []
            if args.dataset == "abcd-replay":
                history[convo], cross_turn = merge_prediction(
                    history.get(convo, {}), facts, conflicts
                )
            record = {
                "run_id": ident,
                "id": sample_id(example),
                "convo_id": convo,
                "template_group": example.get("template_group"),
                "text": text,
                "pending_question": pending,
                "case_before": case.model_dump(mode="json"),
                "case_after": history.get(convo) if args.dataset == "abcd-replay" else None,
                "state_conflicts": cross_turn,
                "expected": example["expected"],
                "label_mask": example["label_mask"],
                "absence_audited": example.get("absence_audited", []),
                "actual": facts.model_dump(mode="json"),
                "rule_candidates": rule_facts.model_dump(mode="json"),
                "model_raw_output": capture.bodies[-1] if capture.bodies else None,
                **provider.last_trace,
                "diagnostics": provider.last_diagnostics,
                "conflicts": conflicts,
                "path": getattr(extractor, "last_path", "rules"),
                "error_categories": categories,
                "usage": {
                    key: sum(int(b.get(key, 0)) for b in capture.bodies if isinstance(b, dict))
                    for key in ("prompt_eval_count", "eval_count", "load_duration")
                },
                "model_calls": capture.calls,
                "seconds": elapsed,
                "error": error,
            }
            handle.write(json.dumps(record) + "\n")
            handle.flush()
            rows.append(record)
            processed += 1
            save()
            print(f"{args.name}: {len(rows)}/{len(selected)} {elapsed:.2f}s", flush=True)
    save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        required=True,
        choices=[
            "apparel-dev",
            "apparel-validation",
            "apparel-regression",
            "abcd-full",
            "abcd-replay",
        ],
    )
    parser.add_argument("--revision", required=True, choices=["v3", "v4"])
    parser.add_argument("--mode", choices=["rules", "hybrid"], default="hybrid")
    parser.add_argument("--name", required=True)
    parser.add_argument("--max-wall-seconds", type=float, required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()
    if args.mode == "rules":
        asyncio.run(run(args))
    else:
        with RepairBudget() as budget:
            args.max_wall_seconds = min(args.max_wall_seconds, budget.remaining_seconds)
            asyncio.run(run(args))
