"""One-shot, serial validation worker; never merges, deploys, trains, or starts Docker."""

import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import signal
import sqlite3
import subprocess
import sys
from collections import Counter
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import httpx

from scripts.local_demo import require_free_port
from scripts.report_optimization import build
from scripts.smoke_app import run_smoke

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/evaluation_runs/extraction-optimization"
RESULTS = ROOT / "docs/results"
BRANCH = "codex/extraction-data-optimization"
CANDIDATE_SHA256 = "4281bb8989f6d9bcff75fdd4c54f29dd8f47b9712ad5b007faf9ddb8fa617c3c"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def candidate_hash():
    snapshot = ROOT / "app/extractors/frozen_v3"
    if snapshot.exists():
        manifest = json.loads((snapshot / "manifest.json").read_text())
        blocks = []
        for name in sorted(manifest["original_files"]):
            source = (
                (ROOT / "app/extractors" / name)
                if name.startswith("frozen_v2/")
                else snapshot / name
            )
            content = source.read_text()
            if not name.startswith("frozen_v2/") and name.endswith(".py"):
                content = content.replace("app.extractors.frozen_v3.", "app.extractors.")
            blocks.append(content.encode())
        return hashlib.sha256(b"".join(blocks)).hexdigest()
    return hashlib.sha256(
        b"".join(
            p.read_bytes()
            for p in sorted((ROOT / "app/extractors").rglob("*"))
            if p.suffix in {".py", ".md"}
        )
    ).hexdigest()


def live_smoke():
    """Fresh synthetic SQLite DB only; stop exactly the supervisor we created."""
    require_free_port(18620)
    database = ROOT / f"data/local_demo/optimization-qwen-{uuid4().hex}.db"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "scripts.local_demo",
            "--provider",
            "ollama",
            "--api-only",
            "--database",
            str(database),
            "--api-port",
            "18620",
        ],
        cwd=ROOT,
        start_new_session=True,
    )
    try:
        deadline = monotonic() + 30
        with httpx.Client(timeout=1, trust_env=False) as client:
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Isolated HTTP demo failed to start")
                try:
                    if client.get("http://127.0.0.1:18620/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if monotonic() >= deadline:
                    raise RuntimeError("HTTP demo readiness deadline exceeded")
                sleep(0.25)
        result = run_smoke("http://127.0.0.1:18620")
        with sqlite3.connect(database) as connection:
            traces = [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT result FROM tool_calls WHERE tool_name = 'fact_extractor'"
                )
            ]
        result["observed_extraction_paths"] = dict(Counter(t["extraction_path"] for t in traces))
        result["observed_model_attempts"] = sum(
            t.get("diagnostics", {}).get("attempts", 0) for t in traces
        )
        result["all_http_checks_passed"] = result["all_passed"]
        result["real_model_path_observed"] = any(
            t["extraction_path"] == "rules_and_model" for t in traces
        )
        result["all_passed"] = (
            result["all_passed"]
            and result["real_model_path_observed"]
            and not any(t["extraction_path"] == "model_error_rules_fallback" for t in traces)
        )
        return result
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            process.wait(timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true", help="Commit/push only owned reports")
    parser.add_argument("--max-hours", type=float, default=4)
    args = parser.parse_args()
    RUN.mkdir(parents=True, exist_ok=True)
    lock = (RUN / "serial.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if git("branch", "--show-current") != BRANCH:
        raise RuntimeError("Wrong branch; no evaluation or publication performed")
    start_revision = git("rev-parse", "HEAD")
    started = monotonic()
    status = {
        "pid": os.getpid(),
        "started_at": datetime.now(UTC).isoformat(),
        "revision": start_revision,
        "state": "waiting_for_development",
        "finished_suites": [],
        "failed_suites": [],
    }
    owned = [
        RESULTS / f"optimization-dev31-final-{variant}.json"
        for variant in ("v2-hybrid", "v3-rules", "v3-model", "v3-hybrid")
    ]
    started_inference = False

    def save():
        (RUN / "serial-status.json").write_text(json.dumps(status, indent=2) + "\n")
        (RESULTS / "extraction-optimization-summary.md").write_text(build())

    def preflight():
        if monotonic() - started >= args.max_hours * 3600:
            raise RuntimeError("Wall-time budget reached; unfinished gates remain blocked")
        if git("rev-parse", "HEAD") != start_revision or git("branch", "--show-current") != BRANCH:
            raise RuntimeError("Repository moved during validation; refusing to continue/publish")
        if git(
            "diff",
            "--name-only",
            "--",
            "app",
            "scripts/evaluate_optimization.py",
            "tests/fixtures",
            "pyproject.toml",
            "uv.lock",
        ):
            raise RuntimeError("Candidate code changed; refusing to mix revisions")
        if candidate_hash() != CANDIDATE_SHA256:
            raise RuntimeError("Extractor hash differs from the frozen candidate")
        manifest = json.loads(
            (ROOT / "tests/fixtures/extraction_optimization_manifest_v3_1.json").read_text()
        )
        for path, expected in (
            (RUN / "abcd-reserve.jsonl", manifest["abcd_reserve_sha256"]),
            (
                ROOT / "tests/fixtures/extraction_optimization_v3_1.json",
                manifest["authored_sha256"],
            ),
        ):
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RuntimeError("Frozen evaluation data changed; refusing to continue")
        with httpx.Client(timeout=5) as client:
            models = (
                client.get("http://127.0.0.1:11434/api/tags").raise_for_status().json()["models"]
            )
        expected_digest = "359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7"
        if not any(m["name"] == "qwen3:4b" and m["digest"] == expected_digest for m in models):
            raise RuntimeError("Pinned Qwen3:4B weights unavailable; no model substitution")
        if platform.system() == "Darwin":
            text = subprocess.check_output(["memory_pressure"], text=True)
            match = re.search(r"System-wide memory free percentage: (\d+)%", text)
            if match and int(match.group(1)) < 10:
                raise RuntimeError("Memory pressure safeguard (<10% free); stopping serial worker")

    def command(parts):
        process = subprocess.Popen(parts, cwd=ROOT, start_new_session=True)
        try:
            return process.wait()
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        # The interactive development queue already owns the single inference slot.
        # Wait for its durable reports, not a guessed duration; never run alongside it.
        while not all(
            (RESULTS / f"optimization-dev31-final-{variant}.json").exists()
            and json.loads((RESULTS / f"optimization-dev31-final-{variant}.json").read_text())[
                "complete"
            ]
            for variant in ("v3-model", "v2-hybrid")
        ):
            preflight()
            save()
            sleep(5)
        started_inference = True
        preflight()
        status.update(state="running", suite="actual-http-ollama-smoke")
        save()
        smoke_path = RESULTS / "optimization-http-ollama-smoke.json"
        owned.append(smoke_path)
        try:
            smoke = live_smoke()
        except Exception as error:
            smoke = {"all_passed": False, "error_type": type(error).__name__}
        smoke_path.write_text(json.dumps(smoke, indent=2) + "\n")
        status["finished_suites" if smoke["all_passed"] else "failed_suites"].append(
            "actual-http-ollama-smoke"
        )
        for dataset, prefix in (
            ("apparel-v31", "validation31-frozen"),
            ("abcd-reserve", "abcd-reserve-frozen"),
            ("abcd-public", "abcd-public-frozen"),
            ("abcd-context", "abcd-context-frozen"),
        ):
            for revision, mode in (
                ("v2", "hybrid"),
                ("v3", "rules"),
                ("v3", "model"),
                ("v3", "hybrid"),
            ):
                preflight()
                name = f"{prefix}-{revision}-{mode}"
                report = RESULTS / f"optimization-{name}.json"
                owned.append(report)
                status.update(state="running", suite=name)
                save()
                if report.exists() and json.loads(report.read_text())["complete"]:
                    if (
                        json.loads(report.read_text())["config"]["source_sha256"]
                        != CANDIDATE_SHA256
                    ):
                        raise RuntimeError("Completed report has a different extractor hash")
                    status["finished_suites"].append(name)
                    continue
                parts = [
                    sys.executable,
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
                ]
                code = command(parts)
                complete = report.exists() and json.loads(report.read_text())["complete"]
                status["finished_suites" if code == 0 and complete else "failed_suites"].append(
                    name
                )
                save()
        preflight()
        status.update(state="finished_release_blocked", finished_at=datetime.now(UTC).isoformat())
        save()
        if args.publish:
            # Never sweep user data or unrelated changes into a commit.
            owned += [RESULTS / "extraction-optimization-summary.md"]
            paths = [str(p.relative_to(ROOT)) for p in owned if p.exists()]
            subprocess.run(["git", "add", "--", *paths], cwd=ROOT, check=True)
            staged = set(git("diff", "--cached", "--name-only").splitlines())
            if not staged.issubset(set(paths)):
                raise RuntimeError("Unrelated staged changes present; publication stopped")
            subprocess.run(["git", "diff", "--cached", "--check"], cwd=ROOT, check=True)
            if staged:
                subprocess.run(
                    [
                        "git",
                        "commit",
                        "-m",
                        "Record serial validation results with release gates blocked",
                    ],
                    cwd=ROOT,
                    check=True,
                )
                subprocess.run(
                    ["git", "push", "origin", BRANCH],
                    cwd=ROOT,
                    check=True,
                    env={**os.environ, "GIT_SSH_COMMAND": "ssh -o BatchMode=yes"},
                )
            status.update(
                state="reported_release_blocked", report_revision=git("rev-parse", "HEAD")
            )
            (RUN / "serial-status.json").write_text(json.dumps(status, indent=2) + "\n")
    except (Exception, KeyboardInterrupt) as error:
        status.update(state="stopped_incomplete_release_blocked", stop_reason=str(error))
        save()
        raise
    finally:
        # Release this task's model allocation; do not kill unrelated applications.
        if started_inference:
            with httpx.Client(timeout=5) as client, suppress(httpx.HTTPError):
                client.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={
                        "model": "qwen3:4b",
                        "keep_alive": 0,
                    },
                ).raise_for_status()


if __name__ == "__main__":
    main()
