"""Paired, fixed-prompt diagnostics; not model qualification or production approval."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import platform
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

from app.config import Settings
from app.extractors.apparel_llm import VERSION, LLMFactExtractor
from app.extractors.base import ExtractorError
from app.services.apparel_service import PROMPTS
from scripts.qualify_apparel_model import FIELDS, summary

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/guardrails_v4_apparel.json"
LIMIT = 5400


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scored_labels(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row["expected"].items()
        if key in FIELDS and row["label_mask"].get(key)
    }


def check_identity(path: Path, identity: dict[str, Any]) -> None:
    if path.exists() and json.loads(path.read_text()) != identity:
        raise ValueError("Changed evaluation identity: use a NEW output directory")
    path.write_text(json.dumps(identity, indent=2))


def compare(rows: dict[str, list[dict[str, Any]]], samples: list[dict[str, Any]]) -> dict[str, Any]:
    models = list(rows)
    ids = {row["id"] for row in samples}
    common = ids.intersection(*({row["id"] for row in values} for values in rows.values()))
    result: dict[str, Any] = {
        "status": "provisional_diagnostic_only",
        "expected_rows_per_model": len(samples),
        "paired_rows": len(common),
        "paired_ids": sorted(common),
        "label_status": "existing assistant-authored provisional regression labels",
        "formal_qualification": False,
        "models": {},
    }
    for model in models:
        values = rows[model]
        attempted = {r["id"] for r in values}
        paired = [r for r in values if r["id"] in common]
        result["models"][model] = {
            "attempted": len(attempted),
            "unfinished_ids": sorted(ids - attempted),
            "all_attempted": summary(values),
            "paired": summary(paired),
            "by_split": {
                split: summary([r for r in values if r.get("split") == split])
                for split in sorted({r.get("split", "unspecified") for r in values})
            },
            "token_subtotals_from_recorded_usage": {
                key: sum(r.get("usage", {}).get(key, 0) for r in values)
                for key in ("prompt_eval_count", "eval_count")
            },
            "rows_without_usage": sum(not r.get("usage") for r in values),
        }
    if len(models) == 2 and common:
        result["paired_known_macro_delta_second_minus_first"] = (
            result["models"][models[1]]["paired"]["known_macro"]
            - result["models"][models[0]]["paired"]["known_macro"]
        )
    return result


async def execute(args: argparse.Namespace) -> None:
    settings = Settings(extraction_mode="llm", llm_provider="ollama", llm_temperature=0, llm_seed=0)
    samples = json.loads(FIXTURE.read_text())
    if len(samples) != 48 or len({r["id"] for r in samples}) != 48:
        raise ValueError("Expected the existing frozen 48 diagnostic rows, without duplicates")
    base = settings.llm_base_url.removesuffix("/v1").rstrip("/")
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(base + "/api/tags")
        response.raise_for_status()
        available = {m["name"]: m["digest"] for m in response.json()["models"]}
        version = (await client.get(base + "/api/version")).json()
    if any(m not in available for m in args.models):
        raise ValueError("Both requested models must already be installed")
    identity = {
        "models_in_execution_order": {m: available[m] for m in args.models},
        "fixture_sha256": digest(FIXTURE),
        "runner_sha256": digest(Path(__file__)),
        "app_source_sha256": hashlib.sha256(
            b"".join(
                p.read_bytes()
                for p in sorted((ROOT / "app").rglob("*"))
                if p.suffix in {".py", ".md", ".json"}
            )
        ).hexdigest(),
        "image_commit": settings.build_commit,
        "spec": VERSION,
        "ollama": version,
        "machine": platform.platform(),
        "temperature": 0,
        "seed": 0,
        "context_tokens": 4096,
        "output_tokens": 512,
        "request_deadline_seconds": 60,
        "shared_budget_seconds": LIMIT,
        "context_protocol": (
            "same as qualify_apparel_model.py; real question mapping, target, selected item"
        ),
    }
    check_identity(args.output / "identity.json", identity)
    ledger_path = args.output / "budget.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"spent_seconds": 0.0}
    rows: dict[str, list[dict[str, Any]]] = {}
    for index, model in enumerate(args.models):
        path = args.output / f"model-{index}.jsonl"
        values = (
            [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        )
        if len({r["id"] for r in values}) != len(values):
            raise ValueError("Duplicate saved results; do not silently rescore them")
        if not {r["id"] for r in values} <= {r["id"] for r in samples}:
            raise ValueError("Saved result IDs do not belong to the frozen fixture")
        rows[model] = values

    def report() -> None:
        body = {
            **compare(rows, samples),
            "identity": identity,
            "spent_seconds": ledger["spent_seconds"],
        }
        (args.output / "comparison.json").write_text(json.dumps(body, indent=2))

    for index, model in enumerate(args.models):
        values = rows[model]
        done = {r["id"] for r in values}
        extractor = LLMFactExtractor(settings.model_copy(update={"llm_model": model}))
        for row in samples:
            if row["id"] in done:
                continue
            if LIMIT - ledger["spent_seconds"] < 60:
                report()
                print(
                    "Stopped at shared 90-minute budget; unfinished rows explicitly reported",
                    flush=True,
                )
                return
            # Reserve the request deadline before calling: a killed process cannot reset its budget.
            ledger["spent_seconds"] += 60
            ledger_path.write_text(json.dumps(ledger))
            started = perf_counter()
            actual, error = {}, None
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
            except ExtractorError as exc:
                error = type(exc.__cause__).__name__ if exc.__cause__ else "ExtractorError"
            elapsed = perf_counter() - started
            output = {
                "id": row["id"],
                "split": row["split"],
                "model": model,
                "expected": scored_labels(row),
                "actual": actual,
                "error": error,
                "seconds": elapsed,
                "usage": extractor.last_usage,
                "rejected_fields": extractor.rejected_fields,
            }
            with (args.output / f"model-{index}.jsonl").open("a") as stream:
                stream.write(json.dumps(output) + "\n")
                stream.flush()
            ledger["spent_seconds"] += elapsed - 60
            ledger_path.write_text(json.dumps(ledger))
            values.append(output)
            report()
            print(
                json.dumps(
                    {
                        "model": model,
                        "done": len(values),
                        "total": len(samples),
                        "error": error,
                        "seconds": round(elapsed, 2),
                    }
                ),
                flush=True,
            )
    print("Completed paired diagnostics. Provisional labels; no production approval.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", nargs=2, default=["qwen3:4b", "qwen3:8b"])
    args = parser.parse_args()
    if len(set(args.models)) != 2:
        parser.error("Use two distinct installed models")
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        asyncio.run(execute(args))


if __name__ == "__main__":
    main()
