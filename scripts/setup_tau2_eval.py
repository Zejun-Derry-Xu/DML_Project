"""Bootstrap the pinned official tau2 text runtime without application dependencies."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.tau2 import OFFICIAL_REVISION  # noqa: E402

OFFICIAL_REPOSITORY = "https://github.com/sierra-research/tau2-bench.git"


def run_command(arguments: list[str], environment: dict[str, str]) -> str:
    result = subprocess.run(
        arguments,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def setup_runtime(source: Path) -> dict[str, Any]:
    source = source.absolute()
    if shutil.which("git") is None or shutil.which("uv") is None:
        raise ValueError("git and uv must be installed before setting up the official runtime")
    environment = os.environ.copy()
    # Explicitly isolate uv even when launched from an active application venv.
    environment["UV_PROJECT_ENVIRONMENT"] = str(source / ".venv")
    environment["PYTHON_DOTENV_DISABLED"] = "1"
    environment["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    environment["LITELLM_TELEMETRY"] = "False"
    if source.exists():
        if not (source / ".git").exists():
            raise ValueError(f"existing path is not an official Git checkout: {source}")
        revision = run_command(["git", "-C", str(source), "rev-parse", "HEAD"], environment)
        if revision != OFFICIAL_REVISION:
            raise ValueError(
                f"existing checkout is at {revision}, expected {OFFICIAL_REVISION}; "
                "choose a new --source path"
            )
        changed = run_command(
            ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"],
            environment,
        )
        if changed:
            raise ValueError(
                "existing official checkout has local changes; choose a new --source path"
            )
        remote = run_command(["git", "-C", str(source), "remote", "get-url", "origin"], environment)
        if remote.removesuffix(".git").rstrip("/") != OFFICIAL_REPOSITORY.removesuffix(".git"):
            raise ValueError("existing checkout origin is not the official tau2 repository")
    else:
        source.parent.mkdir(parents=True, exist_ok=True)
        run_command(
            ["git", "clone", "--no-checkout", OFFICIAL_REPOSITORY, str(source)], environment
        )
        # This is a newly created checkout, never an existing user's working tree.
        run_command(
            ["git", "-C", str(source), "checkout", "--detach", OFFICIAL_REVISION], environment
        )
    run_command(["uv", "sync", "--project", str(source), "--locked", "--no-dev"], environment)
    python = source / ".venv" / "bin" / "python"
    # Required by a top-level upstream text import; no optional voice extra is installed.
    run_command(
        ["uv", "pip", "install", "--python", str(python), "websockets==15.0.1"], environment
    )
    environment["PYTHONPATH"] = str(source / "src")
    environment["TAU2_DATA_DIR"] = str(source / "data")
    run_command([str(python), "-c", "import tau2"], environment)
    return {
        "repository": OFFICIAL_REPOSITORY,
        "revision": OFFICIAL_REVISION,
        "official_source": str(source),
        "tau2_python": str(python),
        "data_dir": str(source / "data"),
        "dependency_setup": "upstream uv.lock base dependencies + websockets==15.0.1",
        "model_requests": 0,
    }


def main() -> None:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument(
        "--source", type=Path, default=Path("data/evaluation_sources/tau2/source")
    )
    parsed = arguments.parse_args()
    try:
        result = setup_runtime(parsed.source)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        raise SystemExit(detail) from error
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
