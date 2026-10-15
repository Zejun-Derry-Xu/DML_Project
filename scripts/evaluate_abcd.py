"""Evaluate existing ReturnFacts extractors on a masked ABCD projection."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from app.evaluation.abcd import (
    ObservedModelExtractor,
    apply_reviewed_annotations,
    load_examples,
    run_evaluation,
    select_examples,
)
from app.evaluation.abcd_adapter import mvp_order_id_projection
from app.extractors.base import FactExtractor
from app.extractors.hybrid import HybridExtractor
from app.extractors.ollama import OllamaExtractor
from app.extractors.rules import RuleBasedExtractor
from scripts.evaluate_reliability import AblationExtractor

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prepared-dir", type=Path, default=ROOT / "data/evaluation_runs/abcd/prepared"
    )
    parser.add_argument("--split", choices=["train", "dev", "test"], default="test")
    parser.add_argument(
        "--task", choices=["self_contained", "contextual", "all"], default="self_contained"
    )
    parser.add_argument("--provider", choices=["rules", "ollama", "hybrid"], default="rules")
    parser.add_argument("--prompt-variant", choices=["focused", "legacy"], default="focused")
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--limit", type=int, help="Independent conversations, never individual turns"
    )
    parser.add_argument("--return-only", action="store_true", help="Native return_* subflow slice")
    parser.add_argument("--time-budget-seconds", type=float)
    parser.add_argument("--request-timeout-seconds", type=float, default=30)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--annotations", type=Path, help="Separate evidence-backed reviewed overlay"
    )
    parser.add_argument(
        "--scorable-only",
        action="store_true",
        help="Select from rows with at least one reviewed field before conversation sampling",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument(
        "--order-id-format",
        choices=["native", "mvp"],
        default="native",
        help="Explicit numeric-ID -> ORD-prefix compatibility experiment, reported separately",
    )
    args = parser.parse_args()
    if args.time_budget_seconds is not None and args.time_budget_seconds <= 0:
        parser.error("--time-budget-seconds must be positive")
    if args.request_timeout_seconds <= 0:
        parser.error("--request-timeout-seconds must be positive")
    if args.provider != "rules" and urlparse(args.base_url).hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        parser.error("Only local Ollama endpoints are supported")
    source = args.prepared_dir / f"{args.split}.jsonl"
    all_examples = load_examples(source)
    annotation_metadata = None
    if args.annotations is not None:
        apply_reviewed_annotations(all_examples, args.annotations)
        overlay = json.loads(args.annotations.read_text())
        annotation_metadata = {
            key: overlay.get(key)
            for key in (
                "annotation_method",
                "reviewer",
                "needs_human_confirmation",
                "selection",
                "selected_convo_ids",
                "source_revision",
                "source_sha256",
            )
        }
    excluded_zero_label_examples = 0
    if args.scorable_only:
        excluded_zero_label_examples = sum(not any(row.label_mask.values()) for row in all_examples)
        all_examples = [row for row in all_examples if any(row.label_mask.values())]
    examples = select_examples(
        all_examples, task=args.task, seed=args.seed, limit=args.limit, return_only=args.return_only
    )
    if args.order_id_format == "mvp":
        examples = mvp_order_id_projection(examples)
    if not examples:
        parser.error("No examples match the selection")
    extractor: FactExtractor
    if args.provider == "rules":
        extractor = RuleBasedExtractor()
    else:
        provider_class = OllamaExtractor if args.prompt_variant == "focused" else AblationExtractor
        options = {"variant": "legacy"} if args.prompt_variant == "legacy" else {}
        model = ObservedModelExtractor(
            provider_class(
                **options,
                base_url=args.base_url,
                model=args.model,
                timeout_seconds=args.request_timeout_seconds,
                retries=0,
            )
        )
        extractor = model if args.provider == "ollama" else HybridExtractor(fallback=model)
    config = {
        "prompt_variant": args.prompt_variant,
        "extractor_source_sha256": hashlib.sha256(
            b"".join(
                (ROOT / path).read_bytes()
                for path in (
                    "app/extractors/rules.py",
                    "app/extractors/hybrid.py",
                    "app/extractors/ollama.py",
                    "app/extractors/contracts.py",
                    "app/extractors/specs/general-v2.md",
                    "app/extractors/specs/apparel-v2.md",
                )
            )
        ).hexdigest(),
        "split": args.split,
        "task": args.task,
        "provider": args.provider,
        "model": args.model if args.provider != "rules" else None,
        "base_url": args.base_url if args.provider != "rules" else None,
        "seed": args.seed,
        "limit_conversations": args.limit,
        "return_only": args.return_only,
        "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "reviewed_annotation_metadata": annotation_metadata,
        "scorable_only": args.scorable_only,
        "excluded_zero_label_examples_in_split": excluded_zero_label_examples,
        "reviewed_annotations_sha256": hashlib.sha256(args.annotations.read_bytes()).hexdigest()
        if args.annotations is not None
        else None,
        "request_timeout_seconds": args.request_timeout_seconds,
        "order_id_adapter": (
            "none; native ABCD identifiers scored unchanged"
            if args.order_id_format == "native"
            else "official-grounded numeric ID -> ORD-prefix compatibility projection"
        ),
    }
    default_name = (
        f"{args.provider}-{args.split}-{args.task}{'-returns' if args.return_only else ''}"
    )
    output = args.output or ROOT / f"data/evaluation_runs/abcd/{default_name}.jsonl"
    summary = await run_evaluation(
        examples,
        extractor,
        output,
        config=config,
        resume=args.resume,
        time_budget_seconds=args.time_budget_seconds,
        request_timeout_seconds=args.request_timeout_seconds,
    )
    summary_path = args.summary or output.with_suffix(".summary.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
