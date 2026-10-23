"""Serial, resumable 8B calibration/validation. Provisional labels are never silently gold."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import math
import platform
from collections import defaultdict
from pathlib import Path
from time import monotonic, perf_counter
from typing import Any

import httpx

from app.config import Settings
from app.extractors.apparel_llm import VERSION as SPEC
from app.extractors.apparel_llm import LLMFactExtractor
from app.extractors.base import ExtractorError
from app.policy.apparel import VERSION
from app.services.apparel_service import PROMPTS

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/guardrails_v4_apparel.json"
REGRESSION = ROOT / "tests/fixtures/extraction_optimization_v3_1.json"
FIELDS = {"stained", "damaged", "tags_attached", "tags_intact", "condition_origin", "used"}
LIMIT = 90 * 60


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    unsupported = errors = 0
    latencies = []
    for row in rows:
        errors += bool(row["error"])
        latencies.append(row["seconds"])
        for field, expected in row["expected"].items():
            actual = row["actual"].get(field)
            if expected is not None:
                counts[field][1] += 1
                counts[field][0] += actual == expected and not row["error"]
            elif actual is not None:
                unsupported += 1
    scores = {
        k: {"correct": v[0], "total": v[1], "accuracy": v[0] / v[1]}
        for k, v in counts.items()
        if v[1]
    }
    ordered = sorted(latencies[1:])  # first request is reported separately as cold/first
    return {
        "fields": scores,
        "known_macro": sum(v["accuracy"] for v in scores.values()) / len(scores) if scores else 0,
        "unsupported_on_reviewed_absence": unsupported,
        "errors": errors,
        "first_seconds": latencies[0] if latencies else None,
        "warm_p95_seconds": ordered[math.ceil(0.95 * len(ordered)) - 1] if ordered else None,
        "calls": len(rows),
        "rows": [r["id"] for r in rows],
    }


async def execute(args: argparse.Namespace) -> None:
    settings = Settings(extraction_mode="llm", llm_provider="ollama", llm_model=args.model)
    base = settings.llm_base_url.removesuffix("/v1").rstrip("/")
    async with httpx.AsyncClient(timeout=5) as client:
        tags = await client.get(base + "/api/tags")
        tags.raise_for_status()
        model = next(m for m in tags.json()["models"] if m["name"] == args.model)
        version = (await client.get(base + "/api/version")).json()
    source_hash = hashlib.sha256(
        b"".join(
            p.read_bytes()
            for p in sorted((ROOT / "app").rglob("*"))
            if p.suffix in {".py", ".json", ".md"}
        )
    ).hexdigest()
    identity = {
        "model": args.model,
        "model_digest": model["digest"],
        "spec": SPEC,
        "commit": settings.build_commit,
        "source_sha256": source_hash,
        "policy_sha256": sha(ROOT / f"app/policy/{VERSION}.json"),
        "fixture_sha256": sha(FIXTURE),
        "regression_sha256": sha(REGRESSION),
        "platform": args.platform,
        "machine": platform.platform(),
        "ollama_version": version,
        "evaluator_sha256": sha(Path(__file__)),
    }
    identity_path = args.output / "identity.json"
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise ValueError(
            "Evaluation identity changed; use a new directory, never reuse other results"
        )
    identity_path.write_text(json.dumps(identity, indent=2))
    ledger_path = args.output / "budget.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"spent_seconds": 0.0}
    fixture = json.loads(FIXTURE.read_text())
    if args.phase == "calibrate":
        suites = [
            (t, seed, [r for r in fixture if r["split"] == "dev"])
            for t in (0, 0.2, 0.7)
            for seed in (0, 1)
        ]
    else:
        calibration = json.loads((args.output / "calibration.json").read_text())
        regression = json.loads(REGRESSION.read_text())
        selected = [r for r in fixture if r["split"] != "dev"] + [
            r for r in regression if r["split"] == "validation"
        ]
        if len(selected) != 204:
            raise ValueError("Expected the frozen 24 validation + 180 regression rows")
        suites = [(calibration["temperature"], 0, selected)]
    all_summaries = []
    for temperature, seed, samples in suites:
        key = f"{args.phase}-t{temperature}-s{seed}"
        path = args.output / f"{key}.jsonl"
        previous = (
            [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        )
        done = {r["id"] for r in previous}
        extractor = LLMFactExtractor(
            settings.model_copy(
                update={
                    "llm_temperature": temperature,
                    "llm_seed": seed,
                }
            )
        )
        for row in samples:
            if row["id"] in done:
                continue
            if LIMIT - ledger["spent_seconds"] < 60:
                print("Stopped: shared 90-minute budget exhausted; unfinished rows retained")
                return
            started = perf_counter()
            error = None
            actual = {}
            try:
                result = await extractor.extract(
                    row["text"],
                    {
                        "question": PROMPTS.get(row.get("pending_question"), "Describe the return"),
                        "target": row.get("pending_question"),
                        "selected_item": row.get("current_case", {}).get("item_name"),
                    },
                )
                actual = {f.field: f.value for f in result.facts if f.state == "stated"}
            except ExtractorError:
                error = "extraction_error"
            elapsed = perf_counter() - started
            ledger["spent_seconds"] += elapsed
            expected = {
                f: v for f, v in row["expected"].items() if f in FIELDS and row["label_mask"].get(f)
            }
            output = {
                "id": row["id"],
                "expected": expected,
                "actual": actual,
                "error": error,
                "seconds": elapsed,
                "usage": extractor.last_usage,
                "rejected_fields": extractor.rejected_fields,
            }
            with path.open("a") as stream:
                stream.write(json.dumps(output) + "\n")
                stream.flush()
            previous.append(output)
            ledger_path.write_text(json.dumps(ledger))
        all_summaries.append({"temperature": temperature, "seed": seed, **summary(previous)})
    if args.phase == "calibrate":
        grouped = []
        for temperature in (0, 0.2, 0.7):
            rows = [r for r in all_summaries if r["temperature"] == temperature]
            grouped.append(
                {
                    "temperature": temperature,
                    "unsupported": sum(r["unsupported_on_reviewed_absence"] for r in rows),
                    "score": sum(r["known_macro"] for r in rows) / len(rows),
                    "errors": sum(r["errors"] for r in rows),
                }
            )
        chosen = min(
            grouped, key=lambda r: (r["unsupported"], r["errors"], -r["score"], r["temperature"])
        )
        (args.output / "calibration.json").write_text(
            json.dumps({**chosen, "suites": all_summaries}, indent=2)
        )
    else:
        stats = all_summaries[0]
        async with httpx.AsyncClient(timeout=5) as client:
            loaded = (await client.get(base + "/api/ps")).json()["models"]
        cpu_only = any(m.get("name") == args.model and m.get("size_vram") == 0 for m in loaded)
        report = {
            **identity,
            **stats,
            "status": "provisional",
            "cpu_only": cpu_only,
            "required_label_review": "dataset SHA256, reviewed_ids and reviewer; all scored IDs",
            "label_status": "automatic provisional labels; human review still required",
            "memory_peak_bytes": None,
            "ollama_image": None,
            "temperature": suites[0][0],
            "completed_at_monotonic": monotonic(),
        }
        (args.output / "qualification.json").write_text(json.dumps(report, indent=2))
    print(f"Completed {args.phase}; results in {args.output}. Not a formal release approval.")


def finalize(args: argparse.Namespace) -> None:
    path = args.output / "qualification.json"
    report = json.loads(path.read_text())
    review = json.loads(args.review.read_text())
    smoke_result = json.loads(args.application_smoke.read_text())
    if (
        not smoke_result.get("model_transport_exercised")
        or smoke_result.get("commit") != report["commit"]
        or smoke_result.get("model") != report["model"]
    ):
        raise ValueError("A matching real-model application smoke is required")
    if (
        review.get("fixture_sha256") != report["fixture_sha256"]
        or review.get("regression_sha256") != report["regression_sha256"]
        or not review.get("reviewer")
        or not set(report["rows"]) <= set(review.get("reviewed_ids", []))
    ):
        raise ValueError("Human review must identify both exact datasets and every scored row")
    report["memory_peak_bytes"] = args.memory_peak_bytes
    report["ollama_image"] = args.ollama_image
    passed = (
        report["calls"] == 204
        and report["known_macro"] >= 0.90
        and report["unsupported_on_reviewed_absence"] == 0
        and report["errors"] == 0
        and report["warm_p95_seconds"] is not None
        and report["warm_p95_seconds"] <= 30
        and report["platform"] == "jetstream-cpu"
        and report["cpu_only"]
        and 0 < args.memory_peak_bytes < 12 * 1024**3
        and bool(args.ollama_image)
        and report["machine"].startswith("Linux")
    )
    report.update(
        status="passed" if passed else "blocked",
        label_status="human_reviewed",
        reviewer=review["reviewer"],
        application_smoke=smoke_result,
    )
    path.write_text(json.dumps(report, indent=2))
    print(report["status"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("calibrate", "validate", "finalize"), required=True)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--platform", choices=("mac-local", "jetstream-cpu"), default="mac-local")
    parser.add_argument("--review", type=Path)
    parser.add_argument("--memory-peak-bytes", type=int, default=0)
    parser.add_argument("--ollama-image")
    parser.add_argument("--application-smoke", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.phase == "finalize":
            if args.review is None or args.application_smoke is None:
                parser.error("--review and --application-smoke are required for finalization")
            finalize(args)
        else:
            asyncio.run(execute(args))


if __name__ == "__main__":
    main()
