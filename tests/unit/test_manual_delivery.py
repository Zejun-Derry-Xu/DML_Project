import argparse
import json
import subprocess

import pytest

from scripts import deploy_release as delivery
from scripts.qualify_apparel_model import summary
from scripts.release_manifest import manifest

COMMIT = "a" * 40
API = "ghcr.io/example/returnflow-api@sha256:" + "1" * 64
FRONTEND = "ghcr.io/example/returnflow-frontend@sha256:" + "2" * 64


def test_manifest_rejects_mutable_tags_and_mixed_format():
    with pytest.raises(ValueError, match="digest"):
        manifest(COMMIT, "ghcr.io/example/api:latest", FRONTEND)
    release = manifest(COMMIT, API, FRONTEND)
    delivery.validate_release(release)
    with pytest.raises(ValueError):
        delivery.validate_release({**release, "schema": "0001"})


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    monkeypatch.setattr(delivery, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("POSTGRES_PASSWORD=never-print-this\n")
    (tmp_path / ".release.env").write_text("old-version\n")
    path = tmp_path / "release.json"
    path.write_text(json.dumps(manifest(COMMIT, API, FRONTEND)))
    args = argparse.Namespace(
        manifest=path, rollback=False, initialize=False, seed_demo=False, qualification=None
    )
    calls = []

    def fake(command, **kwargs):
        calls.append(command)
        if "--format" in command and "config" in command:
            stdout = json.dumps(
                {"services": {"api": {"environment": {"EXTRACTION_MODE": "guided"}}}}
            )
        elif command[:3] == ["docker", "image", "inspect"]:
            stdout = json.dumps(
                [{"Config": {"Labels": {"org.opencontainers.image.revision": COMMIT}}}]
            )
        elif "ps" in command:
            stdout = "test-db-container"
        else:
            stdout = ""
        if "pg_dump" in command:
            kwargs["stdout"].write(b"fake-pg-dump")
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr(delivery, "run", fake)
    monkeypatch.setattr(delivery, "wait_for_release", lambda r: None)
    return tmp_path, args, calls, fake


def test_pull_failure_does_not_stop_or_change_current_images(deployment, monkeypatch):
    root, args, calls, fake = deployment

    def failed(command, **kwargs):
        if command[:2] == ["docker", "pull"]:
            raise subprocess.CalledProcessError(1, command)
        return fake(command, **kwargs)

    monkeypatch.setattr(delivery, "run", failed)
    with pytest.raises(delivery.DeployError) as error:
        delivery.deploy(args)
    assert error.value.code == 2
    assert (root / ".release.env").read_text() == "old-version\n"
    assert not any("stop" in c for c in calls)


def test_migration_failure_retains_backup_and_does_not_switch(deployment, monkeypatch):
    root, args, calls, fake = deployment

    def failed(command, **kwargs):
        if "alembic" in command:
            raise subprocess.CalledProcessError(1, command)
        return fake(command, **kwargs)

    monkeypatch.setattr(delivery, "run", failed)
    with pytest.raises(delivery.DeployError) as error:
        delivery.deploy(args)
    assert error.value.code == 3
    assert (root / ".release.env").read_text() == "old-version\n"
    assert len(list((root / "backups").glob("*.dump"))) == 1
    assert not (root / ".current-release.json").exists()


def test_success_orders_pull_backup_migrate_switch_and_logs_no_password(deployment):
    root, args, calls, _ = deployment
    delivery.deploy(args)
    positions = {
        token: next(i for i, c in enumerate(calls) if token in c)
        for token in ("pull", "pg_dump", "alembic", "up")
    }
    assert positions["pull"] < positions["pg_dump"] < positions["alembic"] < positions["up"]
    assert json.loads((root / ".current-release.json").read_text())["commit"] == COMMIT
    assert "never-print-this" not in (root / "deploy.log").read_text()
    assert not any("downgrade" in c or "--build" in c for c in calls)


def test_arbitrary_rollback_is_rejected_before_docker(deployment):
    root, args, calls, _ = deployment
    (root / ".current-release.json").write_text(json.dumps(manifest(COMMIT, API, FRONTEND)))
    args.rollback = True
    with pytest.raises(ValueError, match="Rollback"):
        delivery.deploy(args)
    assert not calls


def test_older_release_cannot_bypass_rollback_flag(deployment):
    root, args, calls, _ = deployment
    current = manifest("b" * 40, API, FRONTEND, sequence=2)
    (root / ".current-release.json").write_text(json.dumps(current))
    with pytest.raises(ValueError, match="Older release"):
        delivery.deploy(args)
    assert not calls


def test_same_commit_cannot_replace_tested_frontend(deployment):
    root, args, calls, _ = deployment
    current = manifest(COMMIT, API, FRONTEND.replace("2" * 64, "3" * 64))
    (root / ".current-release.json").write_text(json.dumps(current))
    with pytest.raises(ValueError, match="Same commit"):
        delivery.deploy(args)
    assert not calls


@pytest.mark.parametrize("tamper", [False, True])
def test_rollback_requires_exact_pair_evidence(deployment, tamper):
    root, args, calls, _ = deployment
    current = manifest("b" * 40, API, FRONTEND, sequence=2)
    current["compatible_rollbacks"] = [COMMIT]
    current["rollback_evidence"] = {
        COMMIT: {
            "status": "compatible_pair",
            "current_commit": "b" * 40,
            "previous_commit": COMMIT,
            "current_api": API,
            "current_frontend": FRONTEND,
            "previous_api": API,
            "previous_frontend": FRONTEND,
            "schema": "0004",
        }
    }
    if tamper:
        current["rollback_evidence"][COMMIT]["previous_frontend"] = "different-image"
    (root / ".current-release.json").write_text(json.dumps(current))
    args.rollback = True
    if tamper:
        with pytest.raises(ValueError, match="Rollback"):
            delivery.deploy(args)
        assert not calls
    else:
        delivery.deploy(args)
        assert json.loads((root / ".current-release.json").read_text())["commit"] == COMMIT


def test_backup_failure_does_not_migrate_or_switch(deployment, monkeypatch):
    root, args, calls, fake = deployment

    def failed(command, **kwargs):
        if "pg_dump" in command:
            raise subprocess.CalledProcessError(1, command)
        return fake(command, **kwargs)

    monkeypatch.setattr(delivery, "run", failed)
    with pytest.raises(delivery.DeployError) as error:
        delivery.deploy(args)
    assert error.value.code == 3
    assert (root / ".release.env").read_text() == "old-version\n"
    assert not any("alembic" in command for command in calls)


def test_failed_smoke_retains_pending_not_current(deployment, monkeypatch):
    root, args, _, fake = deployment

    def failed(command, **kwargs):
        if "scripts.smoke_apparel" in command:
            raise subprocess.CalledProcessError(1, command)
        return fake(command, **kwargs)

    monkeypatch.setattr(delivery, "run", failed)
    with pytest.raises(delivery.DeployError) as error:
        delivery.deploy(args)
    assert error.value.code == 4
    assert (root / ".pending-release.json").exists()
    assert not (root / ".current-release.json").exists()


def test_llm_deploy_without_qualification_is_rejected_before_pull(deployment, monkeypatch):
    _, args, calls, fake = deployment

    def model_config(command, **kwargs):
        if "config" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "services": {
                            "api": {
                                "environment": {
                                    "EXTRACTION_MODE": "llm",
                                    "LLM_MODEL": "qwen3:4b",
                                }
                            },
                            "ollama": {"image": "ollama/ollama@sha256:" + "3" * 64},
                        }
                    }
                ),
            )
        return fake(command, **kwargs)

    monkeypatch.setattr(delivery, "run", model_config)
    with pytest.raises(ValueError, match="qualification"):
        delivery.deploy(args)
    assert not any(c[:2] == ["docker", "pull"] for c in calls)


def test_metrics_include_false_and_never_score_unreviewed_absence():
    result = summary(
        [
            {
                "id": "one",
                "expected": {"stained": False},
                "actual": {"stained": False},
                "seconds": 1,
                "error": None,
            },
            {
                "id": "two",
                "expected": {"damaged": None},
                "actual": {"damaged": True},
                "seconds": 2,
                "error": None,
            },
        ]
    )
    assert result["fields"]["stained"]["correct"] == 1
    assert result["known_macro"] == 1
    assert result["unsupported_on_reviewed_absence"] == 1
