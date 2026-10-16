"""Shared hard allocation for the single bounded repair round, not per-command resets."""

import fcntl
import json
import platform
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]


def repair_remaining(status):
    return max(
        0.0,
        min(
            5400 - status["repair_seconds"],
            14400 - status["frozen_seconds"] - status["repair_seconds"],
        ),
    )


class RepairBudget:
    def __init__(self, directory=None):
        self.directory = directory or ROOT / "data/evaluation_runs/extraction-optimization"

    def __enter__(self):
        self.lock = (self.directory / "round-v4.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.path = self.directory / "round-v4-budget.json"
            self.status = json.loads(self.path.read_text())
            if self.status["state"] not in {
                "frozen_complete_ready_for_archive",
                "frozen_stopped_budget",
                "repair_ready",
                "repair_stopped_budget",
                "repair_running",
            }:
                raise RuntimeError("Frozen stage has not reached a safe archive boundary")
            if self.status.get("active_started_at"):
                elapsed = (
                    datetime.now(UTC) - datetime.fromisoformat(self.status["active_started_at"])
                ).total_seconds()
                self.status["repair_seconds"] += max(0, elapsed)
            self.remaining_seconds = repair_remaining(self.status)
            if self.remaining_seconds < 60:
                self.status["state"] = "repair_stopped_budget"
                self.status.pop("active_started_at", None)
                self.path.write_text(json.dumps(self.status, indent=2) + "\n")
                raise RuntimeError(
                    "Repair model-evaluation allocation exhausted; no inference started"
                )
            if platform.system() == "Darwin":
                pressure = subprocess.check_output(["memory_pressure"], text=True)
                free = re.search(r"System-wide memory free percentage: (\d+)%", pressure)
                if free and int(free.group(1)) < 10:
                    raise RuntimeError("Memory pressure safeguard; no inference started")
            self.started = monotonic()
            self.status.update(
                state="repair_running", active_started_at=datetime.now(UTC).isoformat()
            )
            self.path.write_text(json.dumps(self.status, indent=2) + "\n")
            return self
        except BaseException:
            self.lock.close()
            raise

    def __exit__(self, exc_type, exc, tb):
        self.status["repair_seconds"] += monotonic() - self.started
        self.status.pop("active_started_at", None)
        self.status["state"] = (
            "repair_stopped_budget" if repair_remaining(self.status) < 60 else "repair_ready"
        )
        if exc_type:
            self.status["repair_last_error_type"] = exc_type.__name__
        self.path.write_text(json.dumps(self.status, indent=2) + "\n")
        self.lock.close()
