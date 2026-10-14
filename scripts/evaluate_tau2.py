"""Run official tau2 retail interactions using only local Ollama models."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.tau2 import Tau2Config, run_evaluation, worker  # noqa: E402


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--official-source", type=Path, default=Path("data/evaluation_sources/tau2/source")
    )
    result.add_argument(
        "--tau2-python", type=Path, help="Python in the separate official tau2 environment"
    )
    result.add_argument(
        "--data-dir", type=Path, help="Official data root containing tau2/domains/retail"
    )
    result.add_argument("--output-dir", type=Path, default=Path("data/evaluation_runs/tau2/local"))
    result.add_argument("--split", default="train", help="Official split (train/test/base) or all")
    result.add_argument("--task-ids", nargs="*", default=[])
    result.add_argument(
        "--num-tasks", type=int, default=1, help="Number of selected tasks; 0 means all"
    )
    result.add_argument("--seeds", type=int, nargs="+", default=[300])
    result.add_argument("--model", default="qwen3:4b")
    result.add_argument("--user-model", default="qwen3:4b")
    result.add_argument("--transport", choices=["ollama", "openai-compatible"], default="ollama")
    result.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    result.add_argument("--max-steps", type=int, default=40)
    result.add_argument("--max-errors", type=int, default=5)
    result.add_argument("--task-timeout-seconds", type=float, default=180)
    result.add_argument("--call-timeout-seconds", type=float, default=60)
    result.add_argument("--total-timeout-seconds", type=float)
    result.add_argument("--max-tokens", type=int, default=512)
    result.add_argument("--num-ctx", type=int, default=4096)
    result.add_argument("--resume", action="store_true")
    result.add_argument("--worker-request", type=Path, help=argparse.SUPPRESS)
    return result


def main() -> None:
    arguments = parser().parse_args()
    if arguments.worker_request:
        worker(arguments.worker_request)
        return
    values = vars(arguments)
    values.pop("worker_request")
    resume = values.pop("resume")
    values["task_ids"] = tuple(values["task_ids"])
    values["seeds"] = tuple(values["seeds"])
    if values["num_tasks"] == 0:
        values["num_tasks"] = None
    config = Tau2Config(**values)
    try:
        report = run_evaluation(config, resume=resume)
    except (ValueError, OSError) as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(report["aggregate"], indent=2))
    print(f"Report: {config.output_dir.resolve() / 'report.json'}")


if __name__ == "__main__":
    main()
