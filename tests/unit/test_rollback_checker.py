"""Control-flow tests only: no Docker process or live database is used here."""

import json
import subprocess

import pytest

from scripts import check_rollback as checker
from scripts.release_manifest import manifest


@pytest.fixture
def compatibility(monkeypatch):
    current = manifest(
        "b" * 40,
        "ghcr.io/x/api@sha256:" + "1" * 64,
        "ghcr.io/x/frontend@sha256:" + "2" * 64,
        sequence=2,
    )
    previous = manifest(
        "a" * 40, "ghcr.io/x/api@sha256:" + "3" * 64, "ghcr.io/x/frontend@sha256:" + "4" * 64
    )
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        stdout = ""
        if "scripts.smoke_apparel" in command:
            stdout = json.dumps({"session_id": "completed-demo"})
        if "scripts.compatibility_fixture" in command:
            stdout = json.dumps({"session_id": "future-demo"})
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    def inspect(command):
        revision = (
            current["commit"]
            if command[-1] in (current["api_image"], current["frontend_image"])
            else previous["commit"]
        )
        return json.dumps(
            [{"Config": {"Labels": {"org.opencontainers.image.revision": revision}}}]
        ).encode()

    def request(opener, base, path, data=None):
        if path in {"/ready", "/version.json"}:
            return {"commit": previous["commit"]}
        if path.endswith("completed-demo"):
            return {"state": "return_created", "return_request": {"id": "preserved"}}
        return {"read_only": True, "question": None, "return_request": None}

    monkeypatch.setattr(checker.subprocess, "run", run)
    monkeypatch.setattr(checker.subprocess, "check_output", inspect)
    monkeypatch.setattr(checker, "request", request)
    return current, previous, calls, run


def test_success_binds_both_image_pairs_and_only_stops_isolated_project(compatibility):
    current, previous, calls, _ = compatibility
    result = checker.check(current, previous, 18517)
    assert result["current_frontend"] == current["frontend_image"]
    assert result["previous_frontend"] == previous["frontend_image"]
    assert result["model_quality_tested"] is False
    compose_calls = [c for c in calls if c[:2] == ["docker", "compose"]]
    assert all(c[3] == "returnflow-compat-" + current["commit"][:10] for c in compose_calls)
    assert compose_calls[-1][-2:] == ["down", "--remove-orphans"]
    assert not any("-v" in c or "--volumes" in c for c in calls)
    assert any(c[-3:] == ["ps", "--all", "-q"] for c in calls)


def test_existing_even_stopped_project_is_never_reused_or_removed(compatibility, monkeypatch):
    current, previous, calls, run = compatibility

    def existing(command, **kwargs):
        result = run(command, **kwargs)
        if "ps" in command:
            result.stdout = "stopped-container"
        return result

    monkeypatch.setattr(checker.subprocess, "run", existing)
    with pytest.raises(ValueError, match="already exists"):
        checker.check(current, previous, 18517)
    assert not any("up" in c or "down" in c for c in calls)


def test_http_failure_never_returns_approval_and_cleans_only_test_project(
    compatibility, monkeypatch
):
    current, previous, calls, _ = compatibility

    def unavailable(*args, **kwargs):
        raise OSError("isolated test API unavailable")

    monkeypatch.setattr(checker, "request", unavailable)
    with pytest.raises(OSError):
        checker.check(current, previous, 18517)
    assert calls[-1][-2:] == ["down", "--remove-orphans"]
