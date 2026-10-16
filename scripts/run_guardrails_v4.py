"""One serial candidate evaluation; no tuning, deployment, Git writes or model substitution."""

import hashlib
import json
import signal
import subprocess
import sys
from pathlib import Path
from time import monotonic

from scripts.evaluate_guardrails_v4 import examples
from scripts.guardrails_budget import RepairBudget, repair_remaining
from scripts.report_guardrails_v4 import build
from scripts.run_optimization_validation import live_smoke

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/evaluation_runs/extraction-optimization"
RESULTS = ROOT / "docs/results"
JOBS = (
    ("apparel-dev", "v4", "hybrid"),
    ("apparel-validation", "v3", "hybrid"),
    ("apparel-validation", "v4", "hybrid"),
    ("apparel-regression", "v4", "rules"),
    ("apparel-regression", "v4", "hybrid"),
    ("abcd-full", "v3", "hybrid"),
    ("abcd-full", "v4", "hybrid"),
    ("abcd-replay", "v3", "hybrid"),
    ("abcd-replay", "v4", "hybrid"),
)


def source_hash():
    return hashlib.sha256(
        b"".join(
            p.read_bytes()
            for p in sorted((ROOT / "app/extractors").rglob("*"))
            if p.suffix in {".py", ".md"}
        )
    ).hexdigest()


def completed_compatible(path, dataset, revision, mode):
    if not path.exists():
        return False
    report = json.loads(path.read_text())
    config = report["config"]
    selected = examples(dataset)
    expected = {
        "dataset": dataset,
        "revision": revision,
        "mode": mode,
        "source_sha256": source_hash(),
        "input_sha256": hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest(),
        "evaluator_sha256": hashlib.sha256(
            (ROOT / "scripts/evaluate_guardrails_v4.py").read_bytes()
        ).hexdigest(),
        "replay_sha256": hashlib.sha256(
            (ROOT / "scripts/guardrails_replay.py").read_bytes()
        ).hexdigest(),
    }
    if any(config.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Existing report identity differs; do not silently reuse or overwrite")
    return report["complete"]


def bounded_smoke(seconds):
    """Interrupt in-process smoke so its finally block stops its exact HTTP supervisor."""

    def deadline(_signum, _frame):
        raise TimeoutError("HTTP acceptance exhausted its reserved wall-time budget")

    previous = signal.signal(signal.SIGALRM, deadline)
    signal.setitimer(signal.ITIMER_REAL, max(1, seconds - 30))
    try:
        return live_smoke()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def main():
    if (
        subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
        != "codex/extraction-guardrails-v4"
    ):
        raise RuntimeError("Run only on the isolated v4 branch after archiving frozen comparisons")
    if not (ROOT / "app/extractors/frozen_v3/manifest.json").exists():
        raise RuntimeError("Verified frozen v3 namespace is required")
    smoke_path = RESULTS / "guardrails-v4-http-smoke.json"
    # Reserve the HTTP acceptance before the longer dataset runs. Never repeat a completed smoke.
    if not smoke_path.exists():
        with RepairBudget() as budget:
            if budget.remaining_seconds < 600:
                raise RuntimeError("Insufficient budget for bounded HTTP smoke; gate remains open")
            started = monotonic()
            try:
                smoke = bounded_smoke(min(600, budget.remaining_seconds))
            except Exception as error:
                smoke = {"all_passed": False, "error_type": type(error).__name__}
            smoke["wall_seconds"] = monotonic() - started
            smoke["source_sha256"] = source_hash()
            smoke["scope"] = "local Apple Metal / synthetic SQLite; not cloud acceptance"
            smoke_path.write_text(json.dumps(smoke, indent=2) + "\n")
        if not smoke["all_passed"]:
            raise RuntimeError("HTTP smoke failed; retain evidence and stop without tuning")
    else:
        smoke = json.loads(smoke_path.read_text())
        if smoke.get("source_sha256") != source_hash():
            raise RuntimeError("Existing HTTP smoke used another source; no automatic repetition")
        if not smoke["all_passed"]:
            raise RuntimeError("Existing HTTP smoke failed; no repetition to erase the failure")
    for dataset, revision, mode in JOBS:
        name = f"guardrails-{dataset}-{revision}-{mode}"
        report = RESULTS / f"optimization-{name}.json"
        while not completed_compatible(report, dataset, revision, mode):
            status = json.loads((RUN / "round-v4-budget.json").read_text())
            remaining = repair_remaining(status)
            if mode != "rules" and remaining < 60:
                (RESULTS / "extraction-guardrails-v4-summary.md").write_text(build())
                print("Repair budget exhausted; missing results remain blocked", flush=True)
                return
            subprocess.run(
                [
                    sys.executable,
                    "-u",
                    "-m",
                    "scripts.evaluate_guardrails_v4",
                    "--dataset",
                    dataset,
                    "--revision",
                    revision,
                    "--mode",
                    mode,
                    "--name",
                    name,
                    "--max-wall-seconds",
                    str(max(60, remaining)),
                    "--batch-size",
                    "16",
                ],
                cwd=ROOT,
                check=True,
            )
            (RESULTS / "extraction-guardrails-v4-summary.md").write_text(build())
    print("Bounded runs complete; labels/cloud gates still block formal release", flush=True)


if __name__ == "__main__":
    main()
