import argparse
import asyncio
import json
import statistics
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app.domain.models import ReturnCase
from app.extractors.base import FactExtractor
from app.extractors.ollama import OllamaExtractor
from app.extractors.rules import RuleBasedExtractor

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "extraction_cases.json"

# Number of follow-up questions after the first customer message for the ten seeded demo cases.
# Confirmation counts because it is a required user answer.
# Terminal policy results ask nothing else.
ADAPTIVE_QUESTIONS = [3, 1, 0, 0, 4, 0, 0, 0, 0, 1]
FIXED_FORM_QUESTIONS = [4] * len(ADAPTIVE_QUESTIONS)


def meaningful(data: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in data.items()
        if value is not None and value is not False and value != "unclear"
    }


async def evaluate_extractor(extractor: FactExtractor) -> dict[str, object]:
    cases = json.loads(FIXTURE.read_text())
    labeled_correct = 0
    labeled_total = 0
    exact = 0
    extra_predictions = 0
    prediction_total = 0
    latencies: list[float] = []
    failures: list[dict[str, object]] = []

    for case in cases:
        started = perf_counter()
        result = await extractor.extract(
            case["text"], ReturnCase(session_id=uuid4()), case.get("pending_question")
        )
        latencies.append((perf_counter() - started) * 1000)
        actual = result.model_dump(mode="json")
        expected = case["expected"]
        mismatches = {
            field: {"expected": value, "actual": actual[field]}
            for field, value in expected.items()
            if actual[field] != value
        }
        labeled_total += len(expected)
        labeled_correct += len(expected) - len(mismatches)
        exact += not mismatches
        predicted = meaningful(actual)
        extra_predictions += sum(field not in expected for field in predicted)
        prediction_total += len(predicted)
        if mismatches:
            failures.append({"text": case["text"], "mismatches": mismatches})

    return {
        "case_count": len(cases),
        "labeled_slot_accuracy": round(labeled_correct / labeled_total, 4),
        "labeled_exact_match": round(exact / len(cases), 4),
        "over_extraction_rate": round(extra_predictions / max(prediction_total, 1), 4),
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 3),
            "p95": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 3),
        },
        "failure_count": len(failures),
        "failures": failures,
    }


def question_efficiency() -> dict[str, object]:
    fixed = statistics.mean(FIXED_FORM_QUESTIONS)
    adaptive = statistics.mean(ADAPTIVE_QUESTIONS)
    return {
        "scenario_count": len(ADAPTIVE_QUESTIONS),
        "fixed_form_average_questions": fixed,
        "adaptive_average_questions": adaptive,
        "question_reduction_percent": round((fixed - adaptive) / fixed * 100, 1),
        "adaptive_questions_by_seed_case": ADAPTIVE_QUESTIONS,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate ReturnFlow fact extraction.")
    parser.add_argument("--provider", choices=["rules", "ollama"], default="rules")
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    extractor: FactExtractor
    if args.provider == "rules":
        extractor = RuleBasedExtractor()
    else:
        extractor = OllamaExtractor(
            base_url=args.base_url,
            model=args.model,
            timeout_seconds=30,
            retries=1,
        )
    output = {
        "provider": args.provider,
        "model": args.model if args.provider == "ollama" else None,
        "extraction": await evaluate_extractor(extractor),
        "question_efficiency": question_efficiency(),
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
