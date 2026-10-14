import argparse
import json

from scripts.run_public_evaluation import build_steps, step_complete


def test_baseline_suite_does_not_start_model_or_container(tmp_path):
    args = argparse.Namespace(
        profile="baseline", run_name=None, report_dir=tmp_path, model_budget_seconds=60
    )
    steps = build_steps(args)
    commands = [step["command"] for step in steps]
    assert all("docker" not in command and "ollama" not in command for command in commands)
    assert not any("scripts.evaluate_tau2" in command for command in commands)
    assert any("scripts.evaluate_abcd" in command and "all" in command for command in commands)


def test_budgeted_partial_run_must_not_be_skipped_on_resume(tmp_path):
    report = tmp_path / "summary.json"
    step = {
        "name": "or-sharc-reader-sample",
        "command": ["python", "--summary", str(report)],
        "marker": tmp_path / "manifest.json",
    }
    report.write_text(
        json.dumps(
            {"retrieval": {"complete": True}, "experiments": {"reader_oracle": {"complete": False}}}
        )
    )
    assert step_complete(step) is False
    report.write_text(
        json.dumps(
            {"retrieval": {"complete": True}, "experiments": {"reader_oracle": {"complete": True}}}
        )
    )
    assert step_complete(step) is True
