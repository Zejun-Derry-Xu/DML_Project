"""Serial paired extraction ablations. Raw records stay ignored; no benchmark gold fabrication."""

import argparse
import asyncio
import hashlib
import json
import math
import platform
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx

from app.domain.models import ReturnCase, ReturnFacts
from app.extractors.base import ExtractorError
from app.extractors.contracts import SPEC_VERSION, prompt
from app.extractors.hybrid import HybridExtractor
from app.extractors.legacy import LEGACY_SYSTEM_PROMPT, LegacyFacts
from app.extractors.ollama import OllamaExtractor
from app.extractors.rules import RuleBasedExtractor

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/extraction_reliability_v2.json"
CRITICAL = ("stained", "tags_attached", "tags_intact", "damaged", "condition_origin")


class AblationExtractor(OllamaExtractor):
    def __init__(self, *, variant: str, **kwargs):
        super().__init__(**kwargs)
        self.variant = variant

    async def extract(self, message, current_case, pending_question):
        if self.variant == "focused":
            return await super().extract(message, current_case, pending_question)
        schema = LegacyFacts if self.variant == "legacy" else ReturnFacts
        if self.variant == "legacy":
            # Exact old context filtering and wording; old schema has eight fields.
            known = {
                key: value
                for key, value in current_case.model_dump(mode="json").items()
                if key in ReturnCase.model_fields
                and key
                not in {
                    "item_category",
                    "stained",
                    "tags_attached",
                    "tags_intact",
                    "condition_origin",
                    "question_prompt",
                }
                and value is not None
                and value is not False
                and value not in {"unclear", "started"}
            }
            system = LEGACY_SYSTEM_PROMPT
            text = (
                "CUSTOMER MESSAGE (extract facts from this text):\n"
                f"{message}\n\nPENDING QUESTION: {pending_question or 'none'}\n"
                "KNOWN CASE FACTS (context only; do not copy them into the extraction):\n"
                f"{json.dumps(known)}"
            )
        else:
            system = "Extract only stated facts as flat ReturnFacts JSON. No evidence envelope."
            text = prompt(message, current_case, pending_question, focused=False)
            text = text.split("OUTPUT SCHEMA:")[0] + (
                f"OUTPUT SCHEMA: {json.dumps(ReturnFacts.model_json_schema())}\n"
                f"CURRENT CUSTOMER MESSAGE:\n{message}"
            )
        payload = {
            "model": self.model,
            "think": False,
            "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}],
            "format": schema.model_json_schema(),
            "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 512},
        }
        self.last_usage = {}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                self.base_url.removesuffix("/v1") + "/api/chat", json=payload
            )
            response.raise_for_status()
            body = response.json()
        self.last_usage = {
            key: int(body[key])
            for key in ("prompt_eval_count", "eval_count", "load_duration")
            if key in body
        }
        if body.get("done_reason") == "length":
            raise ExtractorError("truncated")
        return ReturnFacts.model_validate(
            schema.model_validate_json(body["message"]["content"]).model_dump()
        )


def summarize(rows):
    counts = defaultdict(lambda: {"correct": 0, "total": 0})
    missing = fills = fill_total = known = failures = 0
    for row in rows:
        failures += bool(row.get("error"))
        for field, expected in row["expected"].items():
            counts[field]["total"] += 1
            actual = row["actual"].get(field)
            counts[field]["correct"] += not row.get("error") and actual == expected
            if expected is not None and field not in {"intent", "wants_human"}:
                known += 1
                missing += actual is None
            if field not in {"intent", "wants_human"} and actual is not None:
                fill_total += 1
                fills += expected is None
    latencies = sorted(row["seconds"] for row in rows)
    return {
        "examples": len(rows),
        "template_groups": len({row["template_group"] for row in rows}),
        "field_scores": dict(counts),
        "critical_macro_accuracy": statistics.mean(
            counts[field]["correct"] / counts[field]["total"] for field in CRITICAL
        ),
        "known_fact_omission_rate": missing / max(known, 1),
        "unsupported_fill_rate": fills / max(fill_total, 1),
        "unsupported_fills": fills,
        "predicted_values": fill_total,
        "provider_failures": failures,
        "latency_seconds": {
            "p50": statistics.median(latencies),
            "p95": latencies[math.ceil(0.95 * len(latencies)) - 1],
        },
        "input_tokens": sum(row["usage"].get("prompt_eval_count", 0) for row in rows),
        "output_tokens": sum(row["usage"].get("eval_count", 0) for row in rows),
        "model_calls": sum(row["model_called"] for row in rows),
        "cold_load_seconds": sum(row["usage"].get("load_duration", 0) / 1e9 for row in rows),
    }


async def run(args):
    examples = [row for row in json.loads(FIXTURE.read_text()) if row["split"] == args.split]
    if args.diagnostic:
        if args.split != "dev":
            raise ValueError("Diagnostic selection is dev-only")
        # Three variants from each of twelve semantic groups, not just the first seven groups.
        examples = [
            row
            for row in examples
            if int(row["id"].split("-")[1]) < 12 and int(row["id"].split("-")[2]) < 3
        ]
    variants = (
        ("legacy", "described", "focused", "rules", "hybrid")
        if args.variant == "all"
        else (args.variant,)
    )
    args.run_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "machine": platform.platform(),
        "model": args.model,
        "spec_version": SPEC_VERSION,
        "split": args.split,
        "diagnostic": args.diagnostic,
        "fixture_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "label_status": "assistant_authored_requires_human_review",
        "source_hashes": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / "app/extractors").rglob("*"))
            if path.suffix in {".py", ".md"}
        },
        "working_tree_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], text=True
            ).strip()
        ),
    }
    if any(variant != "rules" for variant in variants):
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(args.base_url.removesuffix("/v1") + "/api/tags")
            response.raise_for_status()
            metadata["model_manifest"] = [
                model for model in response.json()["models"] if model["name"] == args.model
            ]
    summary = {
        "metadata": metadata,
        "results": {},
        "release_status": "blocked",
        "unmet_external_gates": [
            "human_label_audit",
            "paired_public_regression",
            "Jetstream2_PostgreSQL_smoke",
            "backup_restore_exercise",
        ],
    }
    for variant in variants:
        provider = AblationExtractor(
            variant="focused" if variant == "hybrid" else variant,
            base_url=args.base_url,
            model=args.model,
            timeout_seconds=60,
            retries=0,
        )
        extractor = (
            RuleBasedExtractor()
            if variant == "rules"
            else HybridExtractor(provider)
            if variant == "hybrid"
            else provider
        )
        records = []
        with (args.run_dir / f"{variant}.jsonl").open("w") as output:
            for index, example in enumerate(examples):
                case = ReturnCase(session_id=uuid4(), **example["current_case"])
                provider.last_usage = {}
                started = perf_counter()
                error = None
                try:
                    result = await extractor.extract(
                        example["text"], case, example["pending_question"]
                    )
                except (ExtractorError, httpx.HTTPError, ValueError, KeyError) as exc:
                    result, error = ReturnFacts(), type(exc).__name__
                path = getattr(extractor, "last_path", variant)
                record = {
                    **example,
                    "actual": result.model_dump(mode="json"),
                    "error": error,
                    "seconds": perf_counter() - started,
                    "usage": provider.last_usage,
                    "path": path,
                    "model_called": variant != "rules" and path != "rules_sufficient",
                }
                records.append(record)
                output.write(json.dumps(record) + "\n")
                output.flush()
                print(f"{variant}: {index + 1}/{len(examples)}", flush=True)
        summary["results"][variant] = summarize(records)
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant",
        choices=("legacy", "described", "focused", "rules", "hybrid", "all"),
        default="rules",
    )
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--diagnostic", action="store_true")
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434/v1")
    parser.add_argument(
        "--run-dir", type=Path, default=ROOT / "data/evaluation_runs/reliability-v2"
    )
    parser.add_argument(
        "--summary", type=Path, default=ROOT / "docs/results/extraction-reliability-v2.json"
    )
    asyncio.run(run(parser.parse_args()))
