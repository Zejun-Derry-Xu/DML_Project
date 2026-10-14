"""Run a serial, resumable public-data evaluation suite without Docker."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def build_steps(args: argparse.Namespace) -> list[dict[str, Any]]:
    python = sys.executable
    run_root = ROOT / "data/evaluation_runs/public-suite" / (args.run_name or args.profile)
    reports = args.report_dir.resolve()

    def module(name: str) -> list[str]:
        return [python, "-m", f"scripts.{name}"]

    steps: list[dict[str, Any]] = [
        {
            "name": "fetch",
            "command": module("fetch_eval_data"),
            "marker": ROOT / "data/evaluation_sources/abcd/manifest.json",
            "resume": False,
        },
        {
            "name": "prepare-abcd",
            "command": module("prepare_abcd"),
            "marker": ROOT / "data/evaluation_runs/abcd/prepared/manifest.json",
            "resume": False,
        },
    ]
    if args.profile == "baseline":
        steps.extend(
            [
                {
                    "name": "abcd-rules-full-test",
                    "command": module("evaluate_abcd")
                    + [
                        "--provider",
                        "rules",
                        "--task",
                        "all",
                        "--output",
                        str(run_root / "abcd.jsonl"),
                        "--summary",
                        str(reports / "abcd-rules-full-test.json"),
                    ],
                    "marker": run_root / "abcd.jsonl",
                    "resume": True,
                },
                {
                    "name": "or-sharc-full-test",
                    "command": module("evaluate_or_sharc")
                    + [
                        "--mode",
                        "retrieval",
                        "--split",
                        "test",
                        "--retriever",
                        "bm25",
                        "--run-dir",
                        str(run_root / "or-sharc"),
                        "--summary",
                        str(reports / "or-sharc-bm25-test.json"),
                    ],
                    "marker": run_root / "or-sharc/manifest.json",
                    "resume": True,
                },
            ]
        )
        modes = ("rules", "hybrid_rag")
    else:
        for provider in ("rules", "ollama", "hybrid"):
            steps.append(
                {
                    "name": f"abcd-{provider}-sample",
                    "command": module("evaluate_abcd")
                    + [
                        "--provider",
                        provider,
                        "--task",
                        "self_contained",
                        "--scorable-only",
                        "--limit",
                        str(args.conversations),
                        "--seed",
                        "42",
                        "--time-budget-seconds",
                        str(args.model_budget_seconds),
                        "--output",
                        str(run_root / f"abcd-{provider}.jsonl"),
                        "--summary",
                        str(reports / f"abcd-{provider}-sample.json"),
                    ],
                    "marker": run_root / f"abcd-{provider}.jsonl",
                    "resume": True,
                }
            )
        steps.append(
            {
                "name": "or-sharc-reader-sample",
                "command": module("evaluate_or_sharc")
                + [
                    "--mode",
                    "all",
                    "--split",
                    "dev",
                    "--sample-size",
                    str(args.reader_examples),
                    "--seed",
                    "42",
                    "--time-budget-seconds",
                    str(args.model_budget_seconds),
                    "--run-dir",
                    str(run_root / "or-sharc"),
                    "--summary",
                    str(reports / "or-sharc-reader-sample.json"),
                ],
                "marker": run_root / "or-sharc/manifest.json",
                "resume": True,
            }
        )
        modes = ("llm_full_policy", "llm_rag")
    for mode in modes:
        steps.append(
            {
                "name": f"retail-policy-{mode}",
                "command": module("evaluate_return_policy")
                + [
                    "--mode",
                    mode,
                    "--run-path",
                    str(run_root / f"retail-{mode}.json"),
                    "--time-budget-seconds",
                    str(args.model_budget_seconds),
                    "--summary",
                    str(reports / f"return-policy-{mode}.json"),
                ],
                "marker": run_root / f"retail-{mode}.json",
                "resume": True,
            }
        )
    if args.profile == "model-smoke":
        source = args.tau2_source.resolve()
        if not (source / ".venv/bin/python").exists():
            steps.append(
                {
                    "name": "setup-tau2",
                    "command": module("setup_tau2_eval") + ["--source", str(source)],
                    "marker": source / ".venv/bin/python",
                    "resume": False,
                }
            )
        steps.append(
            {
                "name": "tau2-official-train-smoke",
                "command": module("evaluate_tau2")
                + [
                    "--official-source",
                    str(source),
                    "--task-ids",
                    "48",
                    "--split",
                    "train",
                    "--num-tasks",
                    "1",
                    "--seeds",
                    "300",
                    "--num-ctx",
                    "8192",
                    "--max-steps",
                    "20",
                    "--task-timeout-seconds",
                    "180",
                    "--total-timeout-seconds",
                    "180",
                    "--output-dir",
                    str(run_root / "tau2"),
                ],
                "marker": run_root / "tau2/checkpoint.json",
                "resume": True,
            }
        )
    return steps


def step_complete(step: dict[str, Any]) -> bool:
    command = step["command"]
    if "--summary" in command:
        path = Path(command[command.index("--summary") + 1])
        if not path.exists():
            return False
        report = json.loads(path.read_text())
        if "complete" in report:
            return bool(report["complete"])
        if "completed_all" in report:
            return bool(report["completed_all"])
        if "retrieval" in report:
            return bool(report["retrieval"]["complete"]) and all(
                experiment["complete"] for experiment in report["experiments"].values()
            )
    if step["name"].startswith("tau2-"):
        path = step["marker"].parent / "report.json"
        if not path.exists():
            return False
        report = json.loads(path.read_text())
        return len(report["results"]) == report["requested_simulations"] and all(
            row["status"] != "not_started_budget" for row in report["results"]
        )
    return bool(step["marker"].exists())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("baseline", "model-smoke"), default="baseline")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "docs/results/public-eval")
    parser.add_argument("--conversations", type=int, default=32)
    parser.add_argument("--reader-examples", type=int, default=12)
    parser.add_argument("--model-budget-seconds", type=float, default=300)
    parser.add_argument(
        "--tau2-source", type=Path, default=ROOT / "data/evaluation_sources/tau2/source"
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--run-name", help="Use a new name when changing a sample or experiment configuration"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.run_name and (not args.run_name.replace("-", "").replace("_", "").isalnum()):
        parser.error("run-name accepts only letters, digits, hyphens and underscores")
    if min(args.conversations, args.reader_examples, args.model_budget_seconds) <= 0:
        parser.error("Sample sizes and time budget must be positive")
    steps = build_steps(args)
    if args.dry_run:
        print(
            json.dumps(
                [{k: str(v) if isinstance(v, Path) else v for k, v in s.items()} for s in steps],
                indent=2,
            )
        )
        return
    run_root = ROOT / "data/evaluation_runs/public-suite" / (args.run_name or args.profile)
    journal = run_root / "suite.json"
    run_root.mkdir(parents=True, exist_ok=True)
    recorded = json.loads(journal.read_text()) if args.resume and journal.exists() else {}
    for step in steps:
        name, command = step["name"], step["command"]
        fingerprint = hashlib.sha256(json.dumps(command).encode()).hexdigest()
        previous = recorded.get(name)
        if previous and previous["fingerprint"] != fingerprint:
            raise ValueError(f"Resume parameters changed at {name}; choose a new report/run")
        if previous and previous["returncode"] == 0 and step_complete(step) and name != "fetch":
            print(json.dumps({"step": name, "status": "already_completed"}), flush=True)
            continue
        if args.resume and step["resume"] and step["marker"].exists():
            command = [*command, "--resume"]
        print(json.dumps({"step": name, "status": "running"}), flush=True)
        log_path = run_root / f"{name}.log"
        with log_path.open("w") as log:
            completed = subprocess.run(
                command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False
            )
        recorded[name] = {
            "fingerprint": fingerprint,
            "command": command,
            "returncode": completed.returncode,
            "complete": step_complete(step),
            "log": str(log_path.relative_to(ROOT)),
        }
        journal.write_text(json.dumps(recorded, indent=2) + "\n")
        if completed.returncode != 0:
            raise RuntimeError(f"{name} failed; inspect {log_path}, fix, then use --resume")
        print(
            json.dumps(
                {
                    "step": name,
                    "status": "finished" if recorded[name]["complete"] else "budgeted_partial",
                }
            ),
            flush=True,
        )
    print(
        json.dumps(
            {
                "profile": args.profile,
                "report_dir": str(args.report_dir),
                "note": (
                    "Each report states completed counts; a budgeted sample is not full inference."
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
