import json
from argparse import Namespace

import pytest

from scripts import evaluate_optimization as evaluation


@pytest.mark.asyncio
async def test_zero_budget_is_incomplete_and_batches_resume_across_report_commits(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(evaluation, "ROOT", tmp_path)
    monkeypatch.setattr(evaluation, "RUN", tmp_path / "raw")
    monkeypatch.setattr(evaluation.platform, "platform", lambda: "unit-test-machine")
    (tmp_path / "docs/results").mkdir(parents=True)
    rows = [
        {
            "id": str(i),
            "current_case": {},
            "text": "I never wore it.",
            "pending_question": "used",
            "expected": {"used": False},
            "label_mask": {"used": True},
        }
        for i in range(2)
    ]
    monkeypatch.setattr(evaluation, "examples", lambda *args: rows)
    monkeypatch.setattr(evaluation.subprocess, "check_output", lambda *a, **k: "commit-a")
    args = Namespace(
        revision="v3",
        dataset="apparel-v31",
        split="dev",
        mode="rules",
        limit=None,
        name="budget",
        batch_size=1,
        max_wall_seconds=0,
    )
    await evaluation.run(args)
    report = tmp_path / "docs/results/optimization-budget.json"
    assert json.loads(report.read_text())["results"]["examples"] == 0
    assert json.loads(report.read_text())["complete"] is False
    args.max_wall_seconds = 30
    await evaluation.run(args)
    assert json.loads(report.read_text())["results"]["examples"] == 1
    monkeypatch.setattr(evaluation.subprocess, "check_output", lambda *a, **k: "commit-b")
    await evaluation.run(args)
    assert json.loads(report.read_text())["complete"] is True
    assert len((tmp_path / "raw/budget.jsonl").read_text().splitlines()) == 2
