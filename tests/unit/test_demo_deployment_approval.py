import pytest

from scripts.deploy_release import demo_exception_allowed
from scripts.release_manifest import manifest


def test_default_release_model_matches_requested_4b_demo():
    image = "ghcr.io/example/app@sha256:" + "b" * 64
    assert manifest("a" * 40, image, image)["model_name"] == "qwen3:4b"


def test_normal_deployment_keeps_qualification_gate():
    assert not demo_exception_allowed("a" * 40, {}, None)


def test_demo_exception_is_explicit_and_commit_bound():
    assert demo_exception_allowed(
        "a" * 40, {"ENVIRONMENT": "jetstream-demo", "DEMO_ENABLED": "true"}, "a" * 40
    )


@pytest.mark.parametrize(
    "env,commit,rollback",
    [
        ({"ENVIRONMENT": "production", "DEMO_ENABLED": "true"}, "a" * 40, False),
        ({"ENVIRONMENT": "jetstream-demo", "DEMO_ENABLED": "false"}, "a" * 40, False),
        ({"ENVIRONMENT": "jetstream-demo", "DEMO_ENABLED": "true"}, "b" * 40, False),
        ({"ENVIRONMENT": "jetstream-demo", "DEMO_ENABLED": "true"}, "a" * 40, True),
    ],
)
def test_demo_exception_cannot_authorize_production_stale_commit_or_rollback(env, commit, rollback):
    with pytest.raises(ValueError):
        demo_exception_allowed("a" * 40, env, commit, rollback)
