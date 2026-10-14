"""Run the small gold-JSON retail policy supplement separately from public benchmarks."""

import argparse
import json
from pathlib import Path

from app.evaluation.return_policy import evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("rules", "llm_full_policy", "llm_rag", "hybrid_rag"), default="rules"
    )
    parser.add_argument(
        "--run-path", type=Path, default=Path("data/evaluation_runs/return_policy.json")
    )
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--model", default="qwen3:4b")
    parser.add_argument("--time-budget-seconds", type=float, default=600)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    report = evaluate(
        mode=args.mode,
        run_path=args.run_path,
        model=args.model,
        time_budget=args.time_budget_seconds,
        timeout=args.timeout_seconds,
        resume=args.resume,
    )
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
