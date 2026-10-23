"""Manual, paired-image deployment. Standard library only; never rebuild or downgrade data."""

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
IMAGE = re.compile(r"ghcr\.io/[a-z0-9_./-]+@sha256:[a-f0-9]{64}\Z")


class DeployError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(message)


def validate_release(release: dict[str, Any]) -> None:
    if release.get("format") != 1 or not re.fullmatch(r"[a-f0-9]{40}", release.get("commit", "")):
        raise ValueError("Invalid release format or commit")
    if any(not IMAGE.fullmatch(release.get(key, "")) for key in ("api_image", "frontend_image")):
        raise ValueError("Use paired immutable GHCR digest images, never latest or mutable tags")
    if release.get("schema") != "0004" or release.get("workflow") != "apparel":
        raise ValueError("This operator bundle supports schema 0004 / apparel only")
    if type(release.get("sequence")) is not int or release["sequence"] < 1:
        raise ValueError("Release sequence must be a positive CI run number")
    if not re.fullmatch(r"[a-f0-9]{64}", release.get("policy_sha256", "")):
        raise ValueError("Policy digest is required")
    if not re.fullmatch(r"apparel-\d+\.\d+\.\d+", release.get("policy_version", "")):
        raise ValueError("Unsupported policy")


def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(command, check=True, **kwargs)


def atomic_text(path: Path, content: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def log(event: str, commit: str) -> None:
    with (ROOT / "deploy.log").open("a") as stream:
        stream.write(
            json.dumps({"time": datetime.now(UTC).isoformat(), "event": event, "commit": commit})
            + "\n"
        )


def deploy(args: argparse.Namespace) -> None:
    release = json.loads(args.manifest.read_text())
    validate_release(release)
    if not (ROOT / ".env").is_file():
        raise ValueError(
            "Create private .env first; the script never generates or displays passwords"
        )
    current_path = ROOT / ".current-release.json"
    current = json.loads(current_path.read_text()) if current_path.exists() else None
    if current:
        validate_release(current)
        if release["sequence"] < current["sequence"] and not args.rollback:
            raise ValueError("Older release requires an explicitly validated --rollback")
        if release["commit"] == current["commit"] and any(
            release[key] != current[key] for key in ("api_image", "frontend_image")
        ):
            raise ValueError("Same commit cannot silently replace its tested image pair")
    if args.rollback:
        evidence = (current or {}).get("rollback_evidence", {}).get(release["commit"], {})
        expected = {
            "status": "compatible_pair",
            "current_commit": (current or {}).get("commit"),
            "previous_commit": release["commit"],
            "current_api": (current or {}).get("api_image"),
            "current_frontend": (current or {}).get("frontend_image"),
            "previous_api": release["api_image"],
            "previous_frontend": release["frontend_image"],
            "schema": release["schema"],
        }
        if (
            not current
            or release["commit"] not in current.get("compatible_rollbacks", [])
            or any(evidence.get(key) != value for key, value in expected.items())
        ):
            raise ValueError("Rollback pair is not validated; no image/data changes made")
    env_file = ROOT / ".release.env"
    candidate = ROOT / ".candidate-release.env"
    atomic_text(
        candidate, f"API_IMAGE={release['api_image']}\nFRONTEND_IMAGE={release['frontend_image']}\n"
    )
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(ROOT / ".env"),
        "--env-file",
        str(candidate),
        "-f",
        str(ROOT / "compose.jetstream.yml"),
    ]
    # Render only into memory: this contains private environment values; never print it.
    rendered = json.loads(
        run(compose + ["config", "--format", "json"], capture_output=True, text=True).stdout
    )
    api_env = rendered["services"]["api"]["environment"]
    if api_env.get("EXTRACTION_MODE") == "llm":
        full_model_config = json.loads(
            run(
                compose + ["--profile", "model", "config", "--format", "json"],
                capture_output=True,
                text=True,
            ).stdout
        )
        if not re.fullmatch(
            r"ollama/ollama@sha256:[a-f0-9]{64}", full_model_config["services"]["ollama"]["image"]
        ):
            raise ValueError("LLM deployment requires a pinned official Ollama image digest")
        if args.qualification is None:
            raise ValueError(
                "LLM deployment requires a reviewed CPU qualification report; guided is default"
            )
        q = json.loads(args.qualification.read_text())
        if (
            q.get("status") != "passed"
            or q.get("platform") != "jetstream-cpu"
            or q.get("commit") != release["commit"]
            or q.get("model") != api_env.get("LLM_MODEL")
            or q.get("temperature") != float(api_env.get("LLM_TEMPERATURE", 0))
            or q.get("policy_sha256") != release["policy_sha256"]
            or not re.fullmatch(r"[a-f0-9]{64}", q.get("model_digest", ""))
            or q.get("ollama_image") != full_model_config["services"]["ollama"]["image"]
        ):
            raise ValueError("Qualification does not match this CPU release, policy and model")
        compose += ["--profile", "model"]
    try:
        for image in (release["api_image"], release["frontend_image"]):
            run(["docker", "pull", image], stdout=subprocess.DEVNULL)
            metadata = json.loads(
                run(["docker", "image", "inspect", image], capture_output=True, text=True).stdout
            )[0]
            if (
                metadata["Config"].get("Labels", {}).get("org.opencontainers.image.revision")
                != release["commit"]
            ):
                raise DeployError(2, "Image commit label mismatch")
    except subprocess.CalledProcessError as error:
        raise DeployError(2, "Pull/inspect failed; current release unchanged") from error
    if args.initialize:
        run(compose + ["up", "-d", "--wait", "db"])
    if not run(
        compose + ["ps", "--status", "running", "-q", "db"], capture_output=True, text=True
    ).stdout.strip():
        raise ValueError("Database is not running; explicitly use --initialize for first setup")
    backup_dir = ROOT / "backups"
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    backup = backup_dir / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".dump")
    # Stop writes before taking the backup. DB and model volumes are never removed.
    try:
        run(compose + ["stop", "api", "frontend"])
        with backup.open("xb") as stream:
            os.chmod(backup, 0o600)
            run(
                compose
                + ["exec", "-T", "db", "pg_dump", "-U", "returnflow", "-d", "returnflow", "-Fc"],
                stdout=stream,
            )
        with backup.open("rb") as stream:
            run(
                compose + ["exec", "-T", "db", "pg_restore", "--list"],
                stdin=stream,
                stdout=subprocess.DEVNULL,
            )
    except (subprocess.CalledProcessError, OSError) as error:
        raise DeployError(
            3, "Backup failed; app may be stopped, images unchanged; inspect before recovery"
        ) from error
    try:
        run(compose + ["run", "--rm", "--no-deps", "api", "alembic", "upgrade", "head"])
        if args.seed_demo:
            run(
                compose
                + ["run", "--rm", "--no-deps", "api", "python", "-m", "scripts.seed_demo_accounts"]
            )
    except subprocess.CalledProcessError as error:
        # Only expand migrations are permitted. Do not restore data or execute downgrade.
        raise DeployError(
            3, "Migration/seed failed; backup retained, app stopped; inspect before recovery"
        ) from error
    if current:
        atomic_text(ROOT / ".previous-release.json", json.dumps(current, indent=2))
    atomic_text(env_file, candidate.read_text())
    atomic_text(ROOT / ".pending-release.json", json.dumps(release, indent=2))
    try:
        services = ["db", "api", "frontend"] + (
            ["ollama"] if api_env.get("EXTRACTION_MODE") == "llm" else []
        )
        run(compose + ["up", "-d", "--no-build", "--wait"] + services)
        if api_env.get("EXTRACTION_MODE") == "llm":
            status = read_json("http://127.0.0.1:8000/model/status")
            if status.get("digest") != q["model_digest"]:
                raise DeployError(4, "Loaded model manifest differs from qualified model")
        wait_for_release(release)
        run(
            compose
            + [
                "exec",
                "-T",
                "api",
                "python",
                "-m",
                "scripts.smoke_apparel",
                "--expected-commit",
                release["commit"],
            ]
        )
    except (subprocess.CalledProcessError, OSError, AssertionError) as error:
        raise DeployError(
            4, "Switch/readiness/smoke failed; pending and previous manifests retained"
        ) from error
    atomic_text(current_path, json.dumps(release, indent=2))
    log("deployed", release["commit"])
    candidate.unlink(missing_ok=True)
    print(
        f"Deployed {release['commit']}. Backup: {backup.name}. "
        "No model quality claim from HTTP smoke."
    )


def read_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)  # type: ignore[no-any-return]


def wait_for_release(release: dict[str, Any]) -> None:
    for _ in range(30):
        try:
            api = read_json("http://127.0.0.1:8000/ready")
            frontend = read_json("http://127.0.0.1:5173/version.json")
            if (
                api.get("commit") == frontend.get("commit") == release["commit"]
                and api.get("policy_version") == release["policy_version"]
                and api.get("schema") == release["schema"]
                and api.get("policy_sha256") == release["policy_sha256"]
            ):
                return
        except (OSError, ValueError):
            pass
        time.sleep(2)
    raise DeployError(4, "Paired version/schema readiness did not match within the startup window")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--seed-demo", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--qualification", type=Path)
    args = parser.parse_args()
    with (ROOT / ".deploy.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            deploy(args)
        except (DeployError, ValueError, OSError, subprocess.CalledProcessError) as error:
            code = error.code if isinstance(error, DeployError) else 2
            log(f"failed-stage-{code}", "see-pending-manifest")
            # Never print command/environment dumps which can contain credentials.
            print(
                f"Deployment stopped (stage {code}). "
                "Inspect deploy.log and release manifests; data retained.",
                file=sys.stderr,
            )
            sys.exit(code)


if __name__ == "__main__":
    main()
