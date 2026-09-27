"""Evaluate extractor behavior on the audited ABCD pilot utterances.

The gold file covers only intent and reason for in-scope selected utterances.
Unknown reason is an explicit negative label, not a missing annotation. Results
are for fact extraction only and are not return eligibility scores.
"""

import argparse
import asyncio
import json
from collections import defaultdict
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app.domain.models import ReturnCase
from app.extractors.base import ExtractorError, FactExtractor
from app.extractors.hybrid import HybridExtractor
from app.extractors.ollama import OllamaExtractor
from app.extractors.rules import RuleBasedExtractor

GOLD = Path(__file__).parents[1] / "tests/fixtures/abcd_pilot_annotations.json"


def score(expected: list[str | None], predicted: list[str | None]) -> dict[str, float | int]:
    tp = sum(e is not None and e == p for e, p in zip(expected, predicted, strict=True))
    fp = sum(p is not None and p != e for e, p in zip(expected, predicted, strict=True))
    fn = sum(e is not None and p != e for e, p in zip(expected, predicted, strict=True))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4)
        if precision + recall
        else 0.0,
    }


async def run(rows: list[dict[str, object]], extractor: FactExtractor) -> dict[str, object]:
    gold = json.loads(GOLD.read_text())
    fields: dict[str, dict[str, list[str | None]]] = defaultdict(
        lambda: {"expected": [], "predicted": []}
    )
    failures: list[dict[str, object]] = []
    latencies: list[float] = []
    for row in rows:
        if row["status"] in {"excluded", "out_of_scope"}:
            continue
        convo_id = str(row["convo_id"])
        if convo_id not in gold:
            raise ValueError(f"No manual audit label for conversation {convo_id}")
        started = perf_counter()
        try:
            facts = await extractor.extract(str(row["text"]), ReturnCase(session_id=uuid4()), None)
            actual = {
                "intent": facts.intent,
                "reason": facts.reason.value if facts.reason else None,
            }
        except ExtractorError:
            actual = {"intent": None, "reason": None}
            failures.append({"convo_id": convo_id, "error": "PROVIDER_FAILURE"})
        latencies.append((perf_counter() - started) * 1000)
        expected = {"intent": "return", "reason": gold[convo_id]}
        for name in expected:
            fields[name]["expected"].append(expected[name])
            fields[name]["predicted"].append(actual[name])
        if expected != actual:
            failures.append({"convo_id": convo_id, "expected": expected, "predicted": actual})
    return {
        "evaluated_utterances": len(latencies),
        "metrics": {
            name: score(values["expected"], values["predicted"]) for name, values in fields.items()
        },
        "latency_ms": {
            "mean": round(sum(latencies) / len(latencies), 2),
            "p95": round(sorted(latencies)[int(0.95 * len(latencies)) - 1], 2),
        },
        "failures": failures,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, default=Path("data/abcd_pilot/pilot.json"))
    parser.add_argument("--provider", choices=("rules", "ollama", "hybrid"), default="rules")
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    model = OllamaExtractor(base_url=args.base_url, model=args.model, timeout_seconds=30, retries=0)
    extractor: FactExtractor
    if args.provider == "rules":
        extractor = RuleBasedExtractor()
    elif args.provider == "ollama":
        extractor = model
    else:
        extractor = HybridExtractor(model)
    result = {
        "provider": args.provider,
        "model": args.model if args.provider != "rules" else None,
        "pilot": str(args.pilot),
        "result": await run(json.loads(args.pilot.read_text()), extractor),
    }
    output = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output)
    else:
        print(output)


if __name__ == "__main__":
    asyncio.run(main())
