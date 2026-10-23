"""Local single-4B finite ablation. Private traces; never deployment qualification."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import platform
import statistics
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.extractors.apparel_harness import VERSION, HarnessExtractor
from app.extractors.apparel_llm import LLMFactExtractor
from app.extractors.base import ExtractorError
from app.services.apparel_service import PROMPTS
from scripts.compare_apparel_models import check_identity, scored_labels
from scripts.qualify_apparel_model import summary

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "tests/fixtures/guardrails_v4_apparel.json"
NEW = ROOT / "tests/fixtures/harness_v1_validation.json"
VARIANTS = ("legacy", "typed", "span_ids")
LIMIT = 5400


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_samples() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    old = json.loads(OLD.read_text())
    old = [
        {
            **r,
            "labels": scored_labels(r),
            "target": r.get("pending_question"),
            "item": r.get("current_case", {}).get("item_name"),
        }
        for r in old
    ]
    new_body = json.loads(NEW.read_text())
    new = [
        {**r, "labels": r["expected"], "item": "jacket", "split": "new_validation"}
        for r in new_body["rows"]
    ]
    if len(old) != 48 or len(new) != 48 or len({r["id"] for r in old + new}) != 96:
        raise ValueError("Frozen dataset size or unique IDs changed")
    if Counter(r["split"] for r in old) != {"dev": 24, "validation": 24}:
        raise ValueError("Frozen development/regression split changed")
    return old, new


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    body = summary(rows)
    body.pop("rows")
    known_wrong = known_total = null_total = null_correct = rejected_wrong = 0
    errors: Counter[str] = Counter()
    for r in rows:
        if r["error"]:
            errors[r.get("trace", {}).get("stage", "unknown")] += 1
        for field, value in r["expected"].items():
            if value is None:
                null_total += 1
                null_correct += r["actual"].get(field) is None and not r["error"]
            else:
                known_total += 1
                wrong = r["actual"].get(field) != value or bool(r["error"])
                known_wrong += wrong
                rejected_wrong += wrong and field in r["rejected_fields"]
    body.update(
        {
            "known_correct": known_total - known_wrong,
            "known_total": known_total,
            "reviewed_null_total": null_total,
            "reviewed_null_correct": null_correct,
            "known_wrong_also_rejected": rejected_wrong,
            "mean_seconds": statistics.mean(r["seconds"] for r in rows) if rows else None,
            "median_seconds": statistics.median(r["seconds"] for r in rows) if rows else None,
            "failure_stages": dict(errors),
            "usage_subtotals": {
                k: sum(r["usage"].get(k, 0) for r in rows)
                for k in ("prompt_eval_count", "eval_count")
            },
            "rows_without_usage": sum(not r["usage"] for r in rows),
            "cold_warm_note": (
                "First call excluded from P95; actual cache/load varies, load_ns retained per row"
            ),
        }
    )
    return body


def select_candidate(dev: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    scores = {k: metrics(v) for k, v in dev.items()}
    base = scores["legacy"]
    passing = [
        k
        for k in ("typed", "span_ids")
        if (
            scores[k]["known_macro"] >= base["known_macro"]
            and scores[k]["unsupported_on_reviewed_absence"]
            <= base["unsupported_on_reviewed_absence"]
            and scores[k]["errors"] <= base["errors"]
        )
    ]
    candidates = passing or ["typed", "span_ids"]
    selected = min(
        candidates,
        key=lambda k: (
            scores[k]["unsupported_on_reviewed_absence"],
            scores[k]["errors"],
            -scores[k]["known_macro"],
            scores[k]["mean_seconds"],
            k,
        ),
    )
    return {
        "selected": selected,
        "passed_dev_nonregression": bool(passing),
        "selection_data": "24 historical dev messages only",
        "scores": scores,
        "note": "Best experimental candidate, not a deployment/publish decision",
    }


def make_extractor(settings: Settings, variant: str) -> LLMFactExtractor:
    if variant == "legacy":
        ex: LLMFactExtractor = LLMFactExtractor(settings, capture_diagnostics=True)
    elif variant in {"typed", "span_ids"}:
        from typing import cast

        from app.extractors.apparel_harness import Protocol

        ex = HarnessExtractor(settings, cast(Protocol, variant), capture_diagnostics=True)
    else:
        raise ValueError("Unknown experimental variant")
    ex.max_attempts = 1  # identical single-request limit even for frozen prompt baseline
    return ex


async def execute(args: argparse.Namespace) -> None:
    old, new = load_samples()
    base = args.base_url.rstrip("/").removesuffix("/v1")
    if urlparse(base).hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("This phase is local only; no Jetstream or external LLM access")
    settings = Settings(
        _env_file=None,
        extraction_mode="llm",
        llm_provider="ollama",
        llm_model="qwen3:4b",
        llm_base_url=base + "/v1",
        llm_temperature=0,
        llm_seed=0,
        llm_timeout_seconds=60,
    )
    async with httpx.AsyncClient(timeout=5) as client:
        tags = await client.get(base + "/api/tags")
        tags.raise_for_status()
        model = next(m for m in tags.json()["models"] if m["name"] == "qwen3:4b")
        version = (await client.get(base + "/api/version")).json()
    sources = [p for p in sorted((ROOT / "app").rglob("*")) if p.suffix in {".py", ".json", ".md"}]
    identity = {
        "version": VERSION,
        "model": model,
        "ollama": version,
        "source_hash": hashlib.sha256(b"".join(p.read_bytes() for p in sources)).hexdigest(),
        "runner_hash": digest(Path(__file__)),
        "old_fixture_hash": digest(OLD),
        "new_fixture_hash": digest(NEW),
        "machine": platform.platform(),
        "platform": "local-Mac-not-Jetstream",
        "inference_budget_seconds": LIMIT,
        "options": make_extractor(settings, "legacy").build_payload("", {})["options"],
        "label_status": "provisional_assistant_authored_not_formal_gold",
        "single_attempt": True,
    }
    check_identity(args.output / "identity.json", identity)
    budget_path = args.output / "budget.json"
    ledger = json.loads(budget_path.read_text()) if budget_path.exists() else {"spent_seconds": 0.0}
    path = args.output / "traces.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    keys = {(r["variant"], r["id"]) for r in rows}
    if len(keys) != len(rows):
        raise ValueError("Duplicate trace records")
    sample_ids = {r["id"] for r in old + new}
    if any(r["id"] not in sample_ids or r["variant"] not in VARIANTS for r in rows):
        raise ValueError("Saved results do not belong to this frozen experiment")
    development = {r["id"] for r in old if r["split"] == "dev"}
    choice_path = args.output / "selection.json"

    def report(status: str) -> None:
        selected = json.loads(choice_path.read_text()) if choice_path.exists() else None
        results: dict[str, Any] = {}
        for label, samples in (
            ("development", [r for r in old if r["id"] in development]),
            ("historical_regression", old),
            ("new_validation", new),
        ):
            ids = {r["id"] for r in samples}
            variants = (
                VARIANTS
                if label == "development"
                else (("legacy", selected["selected"]) if selected else ("legacy",))
            )
            results[label] = {}
            for variant in variants:
                values = [r for r in rows if r["variant"] == variant and r["id"] in ids]
                results[label][variant] = {
                    "metrics": metrics(values),
                    "unfinished": sorted(ids - {r["id"] for r in values}),
                }
        output = {
            "status": status,
            "formal_qualification": False,
            "spent_seconds": ledger["spent_seconds"],
            "selection": selected,
            "results": results,
            "identity": identity,
        }
        (args.output / "report.json").write_text(json.dumps(output, indent=2))

    async def batch(variant: str, samples: list[dict[str, Any]]) -> bool:
        ex = make_extractor(settings, variant)
        for sample in samples:
            key = (variant, sample["id"])
            if key in keys:
                continue
            if LIMIT - ledger["spent_seconds"] < 60:
                report("budget_exhausted_unfinished_explicit")
                return False
            ledger["spent_seconds"] += 60  # reserve before request; crash cannot reset budget
            budget_path.write_text(json.dumps(ledger))
            started = perf_counter()
            actual, error = {}, None
            try:
                result = await ex.extract(
                    sample["text"],
                    {
                        "question": PROMPTS.get(sample["target"], "Describe the return"),
                        "target": sample["target"],
                        "selected_item": sample["item"],
                    },
                )
                actual = {f.field: f.value for f in result.facts if f.state == "stated"}
            except ExtractorError as exc:
                error = type(exc.__cause__).__name__ if exc.__cause__ else "ExtractorError"
            elapsed = perf_counter() - started
            row = {
                "id": sample["id"],
                "variant": variant,
                "split": sample["split"],
                "expected": sample["labels"],
                "actual": actual,
                "error": error,
                "seconds": elapsed,
                "usage": ex.last_usage,
                "rejected_fields": ex.rejected_fields,
                "trace": ex.last_trace,
            }
            with path.open("a") as stream:
                stream.write(json.dumps(row) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            rows.append(row)
            keys.add(key)
            ledger["spent_seconds"] += elapsed - 60
            budget_path.write_text(json.dumps(ledger))
            report("running")
            print(
                json.dumps(
                    {
                        "variant": variant,
                        "done": len(rows),
                        "id": sample["id"],
                        "error": error,
                        "seconds": round(elapsed, 2),
                    }
                ),
                flush=True,
            )
        return True

    for variant in VARIANTS:
        if not await batch(variant, [r for r in old if r["id"] in development]):
            return
    choice = select_candidate(
        {k: [r for r in rows if r["variant"] == k and r["id"] in development] for k in VARIANTS}
    )
    check_identity(choice_path, choice)  # immutable before reading new validation outputs
    for variant in ("legacy", choice["selected"]):
        if not await batch(variant, [r for r in old if r["id"] not in development]):
            return
    for variant in ("legacy", choice["selected"]):
        if not await batch(variant, new):
            return
    report("completed_provisional_only")
    print("Completed; no cloud deployment or model qualification performed.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to((ROOT / "data/evaluation_runs").resolve()):
        parser.error("Private raw traces must stay under ignored data/evaluation_runs")
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        asyncio.run(execute(args))


if __name__ == "__main__":
    main()
