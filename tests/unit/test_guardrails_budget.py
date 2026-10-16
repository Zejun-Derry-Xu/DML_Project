import json

import pytest

from scripts.guardrails_budget import RepairBudget, repair_remaining


def test_repair_allocation_does_not_borrow_unused_frozen_time():
    assert repair_remaining({"frozen_seconds": 0, "repair_seconds": 0}) == 5400
    assert repair_remaining({"frozen_seconds": 9000, "repair_seconds": 5400}) == 0
    assert repair_remaining({"frozen_seconds": 9100, "repair_seconds": 5300}) == 0


def test_budget_serializes_and_keeps_spend_between_commands(tmp_path):
    path = tmp_path / "round-v4-budget.json"
    path.write_text(
        json.dumps(
            {
                "state": "frozen_complete_ready_for_archive",
                "frozen_seconds": 100,
                "repair_seconds": 10,
            }
        )
    )
    with RepairBudget(tmp_path) as budget:
        assert budget.remaining_seconds == 5390
        with pytest.raises(BlockingIOError), RepairBudget(tmp_path):
            pytest.fail("Concurrent model evaluation must not start")
    updated = json.loads(path.read_text())
    assert updated["repair_seconds"] >= 10
    assert updated["state"] == "repair_ready"
    assert "active_started_at" not in updated
    updated["repair_seconds"] = 5399
    path.write_text(json.dumps(updated))
    with pytest.raises(RuntimeError, match="exhausted"), RepairBudget(tmp_path):
        pytest.fail("Insufficient budget must not start inference")
