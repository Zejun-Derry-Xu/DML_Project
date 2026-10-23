"""Validate a rollback pair on an isolated PostgreSQL Compose project, never live volumes."""

import argparse
import http.cookiejar
import json
import os
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from scripts.deploy_release import validate_release

ROOT = Path(__file__).resolve().parents[1]


def request(opener: Any, base: str, path: str, data: dict[str, Any] | None = None) -> Any:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(data).encode() if data else None,
        headers={"Content-Type": "application/json"},
    )
    with opener.open(req, timeout=10) as response:
        return json.load(response)


def check(current: dict[str, Any], previous: dict[str, Any], port: int) -> dict[str, Any]:
    for release in (current, previous):
        validate_release(release)
        for key, role in (("api_image", "api"), ("frontend_image", "frontend")):
            subprocess.run(["docker", "pull", release[key]], check=True)
            info = json.loads(
                subprocess.check_output(["docker", "image", "inspect", release[key]])
            )[0]
            if info["Config"]["Labels"]["org.opencontainers.image.revision"] != release["commit"]:
                raise ValueError("Image label does not match compatibility manifest")
            subprocess.run(
                ["docker", "tag", release[key], f"returnflow-{role}:{release['commit']}"],
                check=True,
            )
    env = {**os.environ, "BUILD_COMMIT": current["commit"], "CI_FRONTEND_PORT": str(port)}
    project = "returnflow-compat-" + current["commit"][:10]
    compose = ["docker", "compose", "-p", project, "-f", str(ROOT / "compose.ci.yml")]

    def command(*args: str, capture: bool = False) -> str:
        result = subprocess.run(
            compose + list(args),
            check=True,
            env=env,
            stdout=subprocess.PIPE if capture else None,
            text=True,
        )
        return result.stdout or ""

    if command("ps", "--all", "-q", capture=True).strip():
        raise ValueError("Compatibility project already exists; inspect it, never overwrite it")
    try:
        command("up", "-d", "--wait", "db")
        command("run", "--rm", "--no-deps", "api", "alembic", "upgrade", "head")
        command("run", "--rm", "--no-deps", "api", "python", "-m", "scripts.seed_demo_accounts")
        command("up", "-d", "--wait", "api", "frontend")
        smoke = json.loads(
            command(
                "exec",
                "-T",
                "api",
                "python",
                "-m",
                "scripts.smoke_apparel",
                "--write-demo",
                "--expected-commit",
                current["commit"],
                capture=True,
            )
        )
        future = json.loads(
            command(
                "exec", "-T", "api", "python", "-m", "scripts.compatibility_fixture", capture=True
            )
        )
        command("stop", "api", "frontend")
        env["BUILD_COMMIT"] = previous["commit"]
        command("up", "-d", "--no-build", "--wait", "api", "frontend")
        base = f"http://127.0.0.1:{port}"
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        assert request(opener, base, "/version.json")["commit"] == previous["commit"]
        assert request(opener, base, "/ready")["commit"] == previous["commit"]
        request(
            opener,
            base,
            "/api/v1/demo/session",
            {"customer_id": str(uuid5(NAMESPACE_URL, "returnflow:demo-customer:alice"))},
        )
        case = request(opener, base, f"/api/v1/return-cases/{smoke['session_id']}")
        assert case["state"] == "return_created" and case["return_request"]
        unknown = request(opener, base, f"/api/v1/return-cases/{future['session_id']}")
        assert unknown["read_only"] and unknown["question"] is None
        unchanged = request(
            opener,
            base,
            "/api/v1/chat",
            {"session_id": future["session_id"], "message": "confirm return"},
        )
        assert unchanged["read_only"] and unchanged["return_request"] is None
        return {
            "status": "compatible_pair",
            "current_commit": current["commit"],
            "previous_commit": previous["commit"],
            "current_api": current["api_image"],
            "current_frontend": current["frontend_image"],
            "previous_api": previous["api_image"],
            "previous_frontend": previous["frontend_image"],
            "schema": "0004",
            "tested_at": datetime.now(UTC).isoformat(),
            "model_quality_tested": False,
        }
    finally:
        command("down", "--remove-orphans")  # no volume deletion, only this named test project


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--approved-manifest", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18517)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use a nonprivileged, free loopback port")
    current = json.loads(args.current.read_text())
    previous = json.loads(args.previous.read_text())
    evidence = check(current, previous, args.port)
    current["compatible_rollbacks"] = sorted(
        set(current.get("compatible_rollbacks", []) + [previous["commit"]])
    )
    current.setdefault("rollback_evidence", {})[previous["commit"]] = evidence
    with args.approved_manifest.open("x") as stream:
        json.dump(current, stream, indent=2)
    print("Compatibility passed; new approval manifest created. Live database was not touched.")
