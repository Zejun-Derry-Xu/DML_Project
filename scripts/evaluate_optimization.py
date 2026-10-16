"""Serial resumable extraction evaluation with private stage-by-stage traces."""

import argparse
import asyncio
import gzip
import hashlib
import json
import math
import platform
import statistics
import subprocess
from collections import Counter, defaultdict
from contextlib import suppress
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from uuid import UUID

import httpx

from app.domain.models import ReturnCase, ReturnFacts
from app.evaluation.abcd import SOURCE_SHA256, normalize_value
from scripts.prepare_extraction_optimization import CRITICAL

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/evaluation_runs/extraction-optimization"


def observed_questions(source):
    """Only prior observed agent turns; no scenario, delexed text or future answer."""
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("ABCD context source differs from the pinned official artifact")
    with gzip.open(source, "rt") as handle:
        corpus = json.load(handle)
    questions = {}
    for conversation in corpus["train"]:
        last_agent = ""
        for index, (speaker, text) in enumerate(conversation["original"]):
            if speaker == "agent":
                last_agent = text
            elif speaker == "customer":
                questions[conversation["convo_id"], index] = last_agent
    return questions


def examples(dataset, split):
    if dataset in {"apparel", "old-apparel", "apparel-v31"}:
        name = (
            "extraction_optimization_v3_1"
            if dataset == "apparel-v31"
            else "extraction_optimization_v3"
            if dataset == "apparel"
            else "extraction_reliability_v2"
        )
        rows = json.loads((ROOT / f"tests/fixtures/{name}.json").read_text())
        wanted = split if dataset != "old-apparel" else "dev" if split == "dev" else "test"
        return [r for r in rows if r["split"] == wanted]
    if dataset in {"abcd-reserve", "abcd-context"}:
        rows = [json.loads(s) for s in (RUN / "abcd-reserve.jsonl").read_text().splitlines()]
    else:
        native = "dev" if dataset == "abcd-dev" else "test"
        path = ROOT / f"data/evaluation_runs/abcd/prepared/{native}.jsonl"
        rows = [json.loads(s) for s in path.read_text().splitlines()]
    task = "contextual" if dataset == "abcd-context" else "self_contained"
    if dataset == "abcd-context":
        questions = observed_questions(ROOT / "data/evaluation_sources/abcd/abcd_v1.1.json.gz")
        for row in rows:
            if row["task"] == "contextual":
                row["current_case"] = {
                    **row["current_case"],
                    "question_prompt": questions[row["convo_id"], row["turn_index"]],
                }
    return [
        r
        for r in rows
        if r["task"] == task and (dataset == "abcd-context" or any(r["label_mask"].values()))
    ]


def summarize(rows):
    scores = defaultdict(Counter)
    causes = Counter()
    claims = fills = absence_checks = 0
    for row in rows:
        for field, expected in row["expected"].items():
            if not row["label_mask"].get(field, False):
                continue
            actual = row["actual"].get(field)
            ok = not row["error"] and normalize_value(field, actual) == normalize_value(
                field, expected
            )
            counter = scores[field]
            counter["total"] += 1
            counter["correct"] += ok
            if expected is not None:
                counter["known_total"] += 1
                counter["known_correct"] += ok
                counter["known_omitted"] += actual is None
            cls = str(expected).lower()
            counter[f"class_{cls}_total"] += 1
            counter[f"class_{cls}_correct"] += ok
            if actual is not None:
                claims += 1
                fills += expected is None
            absence_checks += field in row.get("absence_audited", [])
            if not ok:
                causes[row["error_categories"].get(field, "unclassified")] += 1
            if field == "item_name" and actual and expected:
                counter["span_containment_diagnostic"] += (
                    str(expected).casefold() in str(actual).casefold()
                )
    critical = [
        scores[f]["known_correct"] / scores[f]["known_total"]
        for f in CRITICAL
        if scores[f]["known_total"]
    ]
    latencies = sorted(r["seconds"] for r in rows)
    return {
        "examples": len(rows),
        "independent_conversations": len(
            {r["convo_id"] for r in rows if r.get("convo_id") is not None}
        ),
        "template_groups": len({r["template_group"] for r in rows if r.get("template_group")}),
        "per_field": {
            f: {**c, "accuracy": c["correct"] / c["total"]} for f, c in scores.items() if c["total"]
        },
        "critical_known_macro": statistics.mean(critical) if critical else None,
        "audited_unsupported_fills": fills,
        "audited_claims": claims,
        "audited_absence_checks": absence_checks,
        "audited_unsupported_fill_rate": fills / claims if claims and absence_checks else None,
        "error_categories": dict(causes),
        "model_calls": sum(r["model_calls"] for r in rows),
        "errors": sum(bool(r["error"]) for r in rows),
        "provider_fallbacks": sum(r["path"] == "model_error_rules_fallback" for r in rows),
        "tokens": {
            key: sum(r["usage"].get(key, 0) for r in rows)
            for key in ("prompt_eval_count", "eval_count")
        },
        "latency_seconds": {
            "p50": statistics.median(latencies),
            "p95": latencies[math.ceil(0.95 * len(latencies)) - 1],
        }
        if latencies
        else None,
        "cold_load_seconds": sum(r["usage"].get("load_duration", 0) / 1e9 for r in rows),
        "label_status": "automatic_provisional; not a production release or official task score",
    }


class Capture:
    def __init__(self):
        self.client = httpx.AsyncClient
        self.bodies = []
        self.calls = 0

    async def request(self, request):
        if request.url.path.endswith("/api/chat"):
            self.calls += 1

    async def response(self, response):
        await response.aread()
        with suppress(ValueError):
            self.bodies.append(response.json())

    def factory(self, *args, **kwargs):
        hooks = kwargs.setdefault("event_hooks", {})
        hooks.setdefault("request", []).append(self.request)
        hooks.setdefault("response", []).append(self.response)
        return self.client(*args, **kwargs)


async def run(args):
    invocation_started = perf_counter()
    max_wall = getattr(args, "max_wall_seconds", None)
    batch_size = getattr(args, "batch_size", None)
    if args.revision == "v2":
        from app.extractors.frozen_v2.hybrid import HybridExtractor
        from app.extractors.frozen_v2.ollama import OllamaExtractor
        from app.extractors.frozen_v2.rules import RuleBasedExtractor
    else:
        from app.extractors.hybrid import HybridExtractor
        from app.extractors.ollama import OllamaExtractor
        from app.extractors.rules import RuleBasedExtractor

        if args.revision == "rules-fixed":
            from app.extractors.frozen_v2.ollama import OllamaExtractor
    selected = examples(args.dataset, args.split)
    if args.limit:
        selected = selected[: args.limit]
    provider = OllamaExtractor(
        base_url="http://127.0.0.1:11434/v1", model="qwen3:4b", timeout_seconds=60, retries=0
    )
    extractor = (
        RuleBasedExtractor()
        if args.mode == "rules"
        else provider
        if args.mode == "model"
        else HybridExtractor(provider)
    )
    config = {
        "dataset": args.dataset,
        "split": args.split,
        "revision": args.revision,
        "mode": args.mode,
        "limit": args.limit,
        "machine": platform.platform(),
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "working_tree_dirty": bool(
            subprocess.check_output(["git", "diff", "--name-only"], text=True).strip()
        ),
        "source_sha256": hashlib.sha256(
            b"".join(
                p.read_bytes()
                for p in sorted((ROOT / "app/extractors").rglob("*"))
                if p.suffix in {".py", ".md"}
            )
        ).hexdigest(),
        "input_sha256": hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest(),
        "evaluation_protocol": "optimization-v3-budgeted-1",
        "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    if args.mode != "rules":
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get("http://127.0.0.1:11434/api/tags")
            response.raise_for_status()
            config["model_manifest"] = response.json()
    identity = {k: v for k, v in config.items() if k not in {"git_revision", "working_tree_dirty"}}
    run_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    output = RUN / f"{args.name}.jsonl"
    report = ROOT / f"docs/results/optimization-{args.name}.json"
    rows = []
    if output.exists():
        rows = [json.loads(s) for s in output.read_text().splitlines()]
        if any(r["run_id"] != run_id for r in rows):
            raise ValueError("Existing run differs: choose another --name; never overwrite")
    done = {r["id"] for r in rows}
    processed = 0
    stopped_for_budget = False

    def publish_progress():
        report.write_text(
            json.dumps(
                {
                    "config": config,
                    "run_id": run_id,
                    "selected": len(selected),
                    "complete": len(rows) == len(selected),
                    "stopped_for_budget": stopped_for_budget,
                    "elapsed_this_invocation_seconds": perf_counter() - invocation_started,
                    "results": summarize(rows),
                    "release_status": "blocked_pending_human_audit_and_quality_gates",
                },
                indent=2,
            )
            + "\n"
        )

    RUN.mkdir(parents=True, exist_ok=True)
    with output.open("a") as handle:
        for example in selected:
            ident = example.get("id", example.get("sample_id"))
            if ident in done:
                continue
            # Do not manufacture a last-request timeout by shortening its 60s budget.
            required = 60 if args.mode != "rules" else 0
            if max_wall is not None and max_wall - (perf_counter() - invocation_started) < required:
                stopped_for_budget = True
                break
            if batch_size is not None and processed >= batch_size:
                break
            case = ReturnCase(session_id=UUID(int=0), **example["current_case"])
            pending = example.get("pending_question")
            text = example.get("text", example.get("message"))
            rule = RuleBasedExtractor()
            rules = await rule.extract(text, case, pending)
            capture = Capture()
            started = perf_counter()
            error = None
            provider.last_usage = {}
            provider.last_diagnostics = {}
            provider.last_trace = {}
            try:
                with patch("httpx.AsyncClient", capture.factory):
                    actual = await extractor.extract(text, case, pending)
            except Exception as exc:
                actual, error = ReturnFacts(), f"{type(exc).__name__}: {exc}"
            elapsed = perf_counter() - started
            raw = capture.bodies[-1].get("message", {}).get("content") if capture.bodies else None
            # Count native usage even when structured parsing/evidence validation fails.
            native_usage = {
                key: sum(int(body.get(key, 0)) for body in capture.bodies if isinstance(body, dict))
                for key in ("prompt_eval_count", "eval_count", "load_duration")
            }
            trace = getattr(provider, "last_trace", {})
            try:
                envelope = json.loads(raw) if raw else {}
            except ValueError:
                envelope = {}
            model_facts = trace.get("model_candidates", envelope.get("facts", {}))
            grounded_model = trace.get("grounded_model")
            if args.revision in {"v2", "rules-fixed"} and raw:
                from app.extractors.frozen_v2.contracts import EvidenceFacts, grounded

                with suppress(ValueError):
                    grounded_model = grounded(
                        EvidenceFacts.model_validate_json(raw), text, pending
                    )[0].model_dump(mode="json")
            rejected = provider.last_diagnostics.get("rejected_fields", [])
            conflicts = getattr(extractor, "last_conflicts", [])
            categories = {}
            for field, gold in example["expected"].items():
                if actual.model_dump().get(field) == gold:
                    continue
                categories[field] = (
                    "provider_error"
                    if error
                    else "fusion_conflict"
                    if field in conflicts
                    else "evidence_rejection"
                    if field in rejected
                    else "rule_false_assertion"
                    if getattr(rules, field, None) is not None
                    and getattr(rules, field, None) != gold
                    else "rule_omission"
                    if args.mode == "rules" and gold is not None
                    else "model_omission"
                    if gold is not None and model_facts.get(field) is None
                    else "model_semantic_or_span_error"
                )
            row = {
                "run_id": run_id,
                "id": ident,
                "convo_id": example.get("convo_id"),
                "template_group": example.get("template_group"),
                "text": text,
                "pending_question": pending,
                "case_before": example["current_case"],
                "expected": example["expected"],
                "label_mask": example.get(
                    "label_mask", {f: True for f in ReturnFacts.model_fields}
                ),
                "absence_audited": example.get("absence_audited", []),
                "actual": actual.model_dump(mode="json"),
                "rule_candidates": rules.model_dump(mode="json"),
                "model_raw_output": raw,
                "model_candidates": model_facts,
                "grounded_model": grounded_model,
                "rule_diagnostics": getattr(rule, "last_diagnostics", {}),
                "diagnostics": provider.last_diagnostics,
                "conflicts": conflicts,
                "path": getattr(extractor, "last_path", args.mode),
                "error_categories": categories,
                "usage": native_usage,
                "model_calls": capture.calls,
                "seconds": elapsed,
                "error": error,
            }
            handle.write(json.dumps(row) + "\n")
            handle.flush()
            rows.append(row)
            processed += 1
            publish_progress()
            print(f"{args.name}: {len(rows)}/{len(selected)} {elapsed:.2f}s", flush=True)
    publish_progress()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        choices=[
            "apparel",
            "apparel-v31",
            "old-apparel",
            "abcd-dev",
            "abcd-public",
            "abcd-reserve",
            "abcd-context",
        ],
        required=True,
    )
    parser.add_argument("--split", choices=["dev", "validation"], default="dev")
    parser.add_argument("--revision", choices=["v2", "v3", "rules-fixed"], default="v3")
    parser.add_argument("--mode", choices=["rules", "model", "hybrid"], default="hybrid")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--name", required=True)
    parser.add_argument("--max-wall-seconds", type=float)
    parser.add_argument("--batch-size", type=int)
    asyncio.run(run(parser.parse_args()))
