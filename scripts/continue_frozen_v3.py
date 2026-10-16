"""Finish only the frozen v3 comparisons within the approved 150-minute allocation."""

import fcntl
import hashlib
import json
import os
import platform
import re
import signal
import subprocess
import sys
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import httpx

from scripts.evaluate_optimization import examples
from scripts.report_optimization import build
from scripts.run_optimization_validation import CANDIDATE_SHA256, candidate_hash

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/evaluation_runs/extraction-optimization"
RESULTS = ROOT / "docs/results"
EXPECTED_MODEL = "359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7"
JOBS = [
    ("abcd-context", "v2", "hybrid", "abcd-context-frozen-v2-hybrid"),
    ("abcd-context", "v3", "model", "abcd-context-frozen-v3-model"),
    ("abcd-context", "v3", "hybrid", "abcd-context-frozen-v3-hybrid"),
    ("abcd-public", "v3", "hybrid", "abcd-public-frozen-v3-hybrid"),
]


def compatible(report, dataset, revision, mode):
    config = report["config"]
    selected = examples(dataset, "validation")
    input_hash = hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()
    models = config.get("model_manifest", {}).get("models", [])
    return (
        config["source_sha256"] == CANDIDATE_SHA256
        and config["input_sha256"] == input_hash
        and (config["dataset"], config["revision"], config["mode"]) == (dataset, revision, mode)
        and report["selected"] == len(selected)
        and any(m["name"] == "qwen3:4b" and m["digest"] == EXPECTED_MODEL for m in models)
    )


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    with (RUN / "round-v4.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        budget_path = RUN / "round-v4-budget.json"
        status = (
            json.loads(budget_path.read_text())
            if budget_path.exists()
            else {
                "plan": "bounded-guardrails-v4-20261016",
                "frozen_seconds": 0.0,
                "repair_seconds": 0.0,
                "frozen_limit_seconds": 9000,
                "repair_limit_seconds": 5400,
                "finished": [],
            }
        )
        if status.get("active_started_at"):
            if status.get("child_pid"):
                try:
                    os.kill(status["child_pid"], 0)
                except ProcessLookupError:
                    pass
                else:
                    raise RuntimeError(
                        "Previous evaluation child still exists; refuse parallel run"
                    )
            # A crashed invocation is charged conservatively, never silently free.
            elapsed = (
                datetime.now(UTC) - datetime.fromisoformat(status["active_started_at"])
            ).total_seconds()
            status["frozen_seconds"] += max(0, elapsed)
            status.pop("active_started_at", None)
        status.update(pid=os.getpid(), state="running_frozen_v3")

        def save():
            budget_path.write_text(json.dumps(status, indent=2) + "\n")
            (RESULTS / "extraction-optimization-summary.md").write_text(build())

        def stop(_signum, _frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, stop)
        try:
            for dataset, revision, mode, name in JOBS:
                if candidate_hash() != CANDIDATE_SHA256:
                    raise RuntimeError("Frozen extractor changed; refusing mixed-code comparison")
                report_path = RESULTS / f"optimization-{name}.json"
                while True:
                    if report_path.exists():
                        report = json.loads(report_path.read_text())
                        if not compatible(report, dataset, revision, mode):
                            raise RuntimeError(
                                f"Incompatible existing report: {name}; retained untouched"
                            )
                        if report["complete"]:
                            if name not in status["finished"]:
                                status["finished"].append(name)
                            break
                    remaining = min(
                        9000 - status["frozen_seconds"],
                        14400 - status["frozen_seconds"] - status["repair_seconds"],
                    )
                    if remaining < 60:
                        status.update(state="frozen_stopped_budget", suite=name)
                        save()
                        return
                    if platform.system() == "Darwin":
                        pressure = subprocess.check_output(["memory_pressure"], text=True)
                        match = re.search(r"System-wide memory free percentage: (\d+)%", pressure)
                        if match and int(match.group(1)) < 10:
                            raise RuntimeError("Memory safeguard (<10% free)")
                    with httpx.Client(timeout=5) as client:
                        models = (
                            client.get("http://127.0.0.1:11434/api/tags")
                            .raise_for_status()
                            .json()["models"]
                        )
                    if not any(
                        m["name"] == "qwen3:4b" and m["digest"] == EXPECTED_MODEL for m in models
                    ):
                        raise RuntimeError("Pinned model missing; no substitution")
                    status.update(suite=name, active_started_at=datetime.now(UTC).isoformat())
                    save()
                    started = monotonic()
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-u",
                            "-m",
                            "scripts.evaluate_optimization",
                            "--dataset",
                            dataset,
                            "--split",
                            "validation",
                            "--revision",
                            revision,
                            "--mode",
                            mode,
                            "--name",
                            name,
                            "--batch-size",
                            "16",
                            "--max-wall-seconds",
                            str(remaining),
                        ],
                        cwd=ROOT,
                        start_new_session=True,
                    )
                    status["child_pid"] = process.pid
                    save()
                    try:
                        code = process.wait()
                    finally:
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGTERM)
                            process.wait(timeout=10)
                        status["frozen_seconds"] += monotonic() - started
                        status.pop("active_started_at", None)
                        status.pop("child_pid", None)
                        save()
                    if code:
                        raise RuntimeError(f"Evaluation exited {code}: {name}")
            status["state"] = "frozen_complete_ready_for_archive"
            save()
        except (Exception, KeyboardInterrupt) as error:
            status.update(state="frozen_stopped_incomplete", reason=str(error))
            save()
            raise
        finally:
            with httpx.Client(timeout=5) as client, suppress(httpx.HTTPError):
                client.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={"model": "qwen3:4b", "keep_alive": 0},
                ).raise_for_status()


if __name__ == "__main__":
    main()
