from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.evaluation import tau2
from scripts import setup_tau2_eval
from scripts.evaluate_tau2 import parser


def config(tmp_path: Path, **changes: object) -> tau2.Tau2Config:
    return replace(
        tau2.Tau2Config(official_source=tmp_path / "official", output_dir=tmp_path / "results"),
        **changes,
    )


def make_data(tmp_path: Path) -> None:
    retail = tmp_path / "official" / "data" / "tau2" / "domains" / "retail"
    tasks = [
        {
            "id": "0",
            "evaluation_criteria": {"reward_basis": ["DB", "NL_ASSERTION"], "nl_assertions": None},
        },
        {
            "id": "1",
            "evaluation_criteria": {
                "reward_basis": ["DB", "NL_ASSERTION"],
                "nl_assertions": ["Expected statement"],
            },
        },
        {"id": "2", "evaluation_criteria": {"reward_basis": ["DB"]}},
    ]
    tau2.write_json(retail / "tasks.json", tasks)
    tau2.write_json(retail / "split_tasks.json", {"train": ["0", "1"], "test": ["2"]})


def test_cli_supports_all_tasks_seeds_resume_and_budgets() -> None:
    arguments = parser().parse_args(
        [
            "--split",
            "all",
            "--num-tasks",
            "0",
            "--seeds",
            "1",
            "2",
            "--max-steps",
            "12",
            "--task-timeout-seconds",
            "120",
            "--resume",
        ]
    )
    assert arguments.num_tasks == 0
    assert arguments.seeds == [1, 2]
    assert arguments.resume
    assert arguments.max_steps == 12


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:11434",
        "http://example.com",
        "http://localhost.evil",
        "http://user@localhost",
        "http://127.0.0.1/v1",
    ],
)
def test_rejects_nonlocal_or_ambiguous_model_endpoints(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        config(tmp_path, ollama_url=url).validate()


@pytest.mark.parametrize(
    "changes",
    [
        {"seeds": ()},
        {"seeds": (1, 1)},
        {"max_steps": 0},
        {"task_timeout_seconds": float("inf")},
        {"num_tasks": -1},
    ],
)
def test_rejects_invalid_budgets_and_selection(tmp_path: Path, changes: dict) -> None:
    with pytest.raises(ValueError):
        config(tmp_path, **changes).validate()


def test_split_selection_does_not_silently_admit_test_ids(tmp_path: Path) -> None:
    make_data(tmp_path)
    assert [task["id"] for task in tau2.select_tasks(config(tmp_path, num_tasks=None))] == [
        "0",
        "1",
    ]
    with pytest.raises(ValueError, match="not in split"):
        tau2.select_tasks(config(tmp_path, task_ids=("2",)))
    assert [
        task["id"] for task in tau2.select_tasks(config(tmp_path, split="all", task_ids=("2",)))
    ] == ["2"]


def test_empty_nl_assertions_are_locally_scoreable() -> None:
    assert not tau2.needs_external_judge(
        {"evaluation_criteria": {"reward_basis": ["DB", "NL_ASSERTION"], "nl_assertions": None}}
    )
    assert tau2.needs_external_judge(
        {
            "evaluation_criteria": {
                "reward_basis": ["NL_ASSERTION"],
                "nl_assertions": ["expected info"],
            }
        }
    )
    assert not tau2.needs_external_judge(
        {
            "evaluation_criteria": {
                "reward_basis": ["DB"],
                "nl_assertions": ["unused qualitative annotation"],
            }
        }
    )


def test_agent_inputs_contain_only_policy_tools_and_local_llm(tmp_path: Path) -> None:
    environment = Mock()
    environment.get_policy.return_value = "PUBLIC_POLICY"
    environment.get_tools.return_value = ["PUBLIC_TOOL_SCHEMA"]
    arguments = tau2.agent_kwargs(environment, config(tmp_path))
    assert set(arguments) == {"tools", "domain_policy", "llm", "llm_args"}
    assert arguments["domain_policy"] == "PUBLIC_POLICY"
    assert arguments["tools"] == ["PUBLIC_TOOL_SCHEMA"]
    assert "task" not in arguments
    assert "evaluation_criteria" not in json.dumps(arguments)
    assert arguments["llm"] == "ollama_chat/qwen3:4b"
    assert arguments["llm_args"]["num_retries"] == 0
    assert arguments["llm_args"]["reasoning_effort"] == "none"
    assert arguments["llm_args"]["num_ctx"] == 4096


def test_hard_timeout_retains_unscored_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess_run = Mock(side_effect=subprocess.TimeoutExpired("worker", 0.01))
    monkeypatch.setattr(tau2.subprocess, "run", subprocess_run)
    result = tau2.run_one(config(tmp_path), "48", 300, 0.01)
    assert result["status"] == "timeout"
    assert result["official_reward"] is None
    assert result["attempted"] is True
    assert subprocess_run.call_args.kwargs["timeout"] == 0.01
    assert "--worker-request" in subprocess_run.call_args.args[0]
    request = json.loads((tmp_path / "results" / "requests" / "task-48-seed-300.json").read_text())
    assert set(request) == {"config", "task_id", "seed", "result_path", "trajectory_path"}


def test_aggregate_denominators_include_failed_and_unscored_requests() -> None:
    result = tau2.aggregate(
        [
            {"status": "completed", "attempted": True, "official_reward": 1.0},
            {"status": "max_steps", "attempted": True, "official_reward": 0.0},
            {"status": "timeout", "attempted": True, "official_reward": None},
            {"status": "excluded_nl_assertions", "attempted": False, "official_reward": None},
        ],
        requested=5,
    )
    assert result["attempted_simulations"] == 3
    assert result["completed_interactions"] == 1
    assert result["officially_scored_simulations"] == 2
    assert result["unscored_simulations"] == 3
    assert result["mean_official_reward_over_scored"] == 0.5
    assert result["reward_lower_bound_over_requested"] == 0.2
    assert result["score_coverage"] == 0.4
    assert result["official_pass_k"] is None


def test_resume_keeps_terminal_rows_and_exclusions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_data(tmp_path)
    monkeypatch.setattr(tau2, "verify_source", lambda _: {"revision": tau2.OFFICIAL_REVISION})
    runner = Mock(
        return_value={
            "task_id": "0",
            "seed": 300,
            "status": "max_steps",
            "attempted": True,
            "official_reward": 0.0,
        }
    )
    monkeypatch.setattr(tau2, "run_one", runner)
    settings = config(tmp_path, num_tasks=None)
    first = tau2.run_evaluation(settings)
    assert first["aggregate"]["requested_simulations"] == 2
    assert first["aggregate"]["status_counts"] == {"excluded_nl_assertions": 1, "max_steps": 1}
    assert runner.call_count == 1
    tau2.run_evaluation(settings, resume=True)
    assert runner.call_count == 1
    with pytest.raises(ValueError, match="configuration/source"):
        tau2.run_evaluation(replace(settings, max_steps=50), resume=True)


def test_venv_interpreter_path_is_not_resolved_away(tmp_path: Path) -> None:
    python_path = tmp_path / "venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.symlink_to("/usr/bin/python3")
    settings = config(tmp_path, tau2_python=python_path)
    assert settings.serialized()["tau2_python"] == str(python_path)


def test_worker_environment_disables_dotenv_and_cloud_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("HTTPS_PROXY", "http://remote-proxy")
    result = tau2.subprocess_environment(config(tmp_path))
    assert "OPENAI_API_KEY" not in result
    assert "HTTPS_PROXY" not in result
    assert result["PYTHON_DOTENV_DISABLED"] == "1"
    assert result["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"


def test_source_preflight_rejects_wrong_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tau2.subprocess, "check_output", Mock(return_value="wrong-revision"))
    with pytest.raises(ValueError, match="must be pinned"):
        tau2.verify_source(config(tmp_path))


def test_source_preflight_rejects_local_runtime_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        tau2.subprocess,
        "check_output",
        Mock(side_effect=[tau2.OFFICIAL_REVISION, "?? src/tau2/changed.py\n"]),
    )
    with pytest.raises(ValueError, match="local modifications"):
        tau2.verify_source(config(tmp_path))


def test_total_budget_reports_every_requested_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_data(tmp_path)
    monkeypatch.setattr(tau2, "verify_source", lambda _: {"revision": tau2.OFFICIAL_REVISION})
    # No task has started when the clock advances beyond the invocation budget.
    monotonic = Mock(side_effect=[0, 2, 3, 4, 5])
    monkeypatch.setattr(tau2.time, "monotonic", monotonic)
    runner = Mock()
    monkeypatch.setattr(tau2, "run_one", runner)
    report = tau2.run_evaluation(
        config(tmp_path, split="all", num_tasks=None, total_timeout_seconds=1)
    )
    assert runner.call_count == 0
    assert report["aggregate"]["requested_simulations"] == 3
    assert report["aggregate"]["recorded_simulations"] == 3
    assert report["aggregate"]["status_counts"] == {
        "excluded_nl_assertions": 1,
        "not_started_budget": 2,
    }
    assert report["aggregate"]["mean_official_reward_over_scored"] is None
    assert report["aggregate"]["score_coverage"] == 0


def test_setup_rejects_existing_different_checkout_without_checkout_or_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "official"
    (source / ".git").mkdir(parents=True)
    monkeypatch.setattr(setup_tau2_eval.shutil, "which", lambda _: "/tool")
    runner = Mock(return_value="different-revision")
    monkeypatch.setattr(setup_tau2_eval, "run_command", runner)
    with pytest.raises(ValueError, match="choose a new"):
        setup_tau2_eval.setup_runtime(source)
    assert runner.call_count == 1
    assert "checkout" not in runner.call_args.args[0]


def test_setup_rejects_dirty_checkout_before_dependency_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "official"
    (source / ".git").mkdir(parents=True)
    monkeypatch.setattr(setup_tau2_eval.shutil, "which", lambda _: "/tool")
    runner = Mock(side_effect=[tau2.OFFICIAL_REVISION, " M src/tau2/agent/llm_agent.py"])
    monkeypatch.setattr(setup_tau2_eval, "run_command", runner)
    with pytest.raises(ValueError, match="local changes"):
        setup_tau2_eval.setup_runtime(source)
    assert runner.call_count == 2


def test_setup_new_runtime_pins_source_and_keeps_base_dependencies_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(setup_tau2_eval.shutil, "which", lambda _: "/tool")
    runner = Mock(return_value="")
    monkeypatch.setattr(setup_tau2_eval, "run_command", runner)
    source = tmp_path / "official"
    result = setup_tau2_eval.setup_runtime(source)
    commands = [call.args[0] for call in runner.call_args_list]
    assert commands[0] == [
        "git",
        "clone",
        "--no-checkout",
        setup_tau2_eval.OFFICIAL_REPOSITORY,
        str(source),
    ]
    assert commands[1][-2:] == ["--detach", tau2.OFFICIAL_REVISION]
    assert commands[2] == ["uv", "sync", "--project", str(source), "--locked", "--no-dev"]
    assert commands[3][-1] == "websockets==15.0.1"
    assert commands[4][-1] == "import tau2"
    assert all("--extra" not in command for command in commands)
    assert result["model_requests"] == 0
    assert runner.call_args.args[1]["UV_PROJECT_ENVIRONMENT"] == str(source / ".venv")
